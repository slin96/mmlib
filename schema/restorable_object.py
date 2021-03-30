import abc
import configparser
import os
import tempfile
from abc import ABCMeta
from typing import Dict

import torch

from mmlib.constants import MMLIB_CONFIG, VALUES
from mmlib.persistence import AbstractFilePersistenceService, AbstractDictPersistenceService
from schema.schema_obj import SchemaObj
from util.init_from_file import create_object_with_parameters

STATE_DICT = 'state_dict'

ID = 'id'
CODE_FILE = 'code_file'
CLASS_NAME = 'class_name'
IMPORT_CMD = 'import_cmd'
INIT_ARGS = 'init_args'
CONFIG_ARGS = 'config_args'
INIT_REF_TYPE_ARGS = 'init_ref_type_args'
STATE_FILE = 'state_file'

RESTORABLE_OBJECT = 'restorable_object'


class RestoredModelInfo:
    def __init__(self, model: torch.nn.Module, inference_info=None):
        self.model = model
        self.inference_info = inference_info


class AbstractRestorableObjectWrapper(SchemaObj, metaclass=ABCMeta):

    def __init__(self, class_name: str, code: str, import_cmd: str = None, instance: object = None,
                 store_id: str = None):
        super().__init__(store_id)
        self.instance = instance
        self.code = code
        self.class_name = class_name
        self.import_cmd = import_cmd

    def _persist_class_specific_fields(self, dict_representation, file_pers_service, dict_pers_service):

        # mandatory fields
        dict_representation[CLASS_NAME] = self.class_name

        # optional fields
        if self.code:
            assert self.import_cmd is None, 'if code is set then there should be no import cmd'
            code_file_id = file_pers_service.save_file(self.code)
            dict_representation[CODE_FILE] = code_file_id
        if self.import_cmd:
            assert self.code is None, 'if import_cmd is set then there should be no code'
            dict_representation[IMPORT_CMD] = self.import_cmd


class RestorableObjectWrapper(AbstractRestorableObjectWrapper):

    def __init__(self, class_name: str, init_args: dict, init_ref_type_args: [str], config_args: dict, code: str = None,
                 import_cmd: str = None, instance: object = None, store_id: str = None):

        super().__init__(class_name, code, import_cmd=import_cmd, instance=instance, store_id=store_id)

        self.init_args = init_args
        self.config_args = config_args
        self.init_ref_type_args = init_ref_type_args

    def set_instance(self, instance):
        self.instance = instance

    def _persist_class_specific_fields(self, dict_representation, file_pers_service, dict_pers_service):

        super()._persist_class_specific_fields(dict_representation, file_pers_service, dict_pers_service)

        dict_representation[INIT_ARGS] = self.init_args
        dict_representation[CONFIG_ARGS] = self.config_args
        dict_representation[INIT_REF_TYPE_ARGS] = self.init_ref_type_args

    @classmethod
    def load(cls, obj_id: str, file_pers_service: AbstractFilePersistenceService,
             dict_pers_service: AbstractDictPersistenceService, restore_root: str):
        restored_dict = dict_pers_service.recover_dict(obj_id, RESTORABLE_OBJECT)

        class_name, code_file_path, config_args, import_cmd, init_args, ref_type_args = cls._restore_fields(
            file_pers_service, restore_root, restored_dict)

        restorable_obj_wrapper = cls(store_id=obj_id, code=code_file_path, class_name=class_name, import_cmd=import_cmd,
                                     init_args=init_args, init_ref_type_args=ref_type_args, config_args=config_args)

        return restorable_obj_wrapper

    @classmethod
    def _restore_fields(cls, file_pers_service, restore_root, restored_dict):
        class_name = restored_dict[CLASS_NAME]
        init_args = restored_dict[INIT_ARGS]
        config_args = restored_dict[CONFIG_ARGS]
        ref_type_args = restored_dict[INIT_REF_TYPE_ARGS]
        code_file_path = None
        if CODE_FILE in restored_dict:
            code_file_id = restored_dict[CODE_FILE]
            code_file_path = file_pers_service.recover_file(code_file_id, restore_root)
        import_cmd = restored_dict[IMPORT_CMD] if IMPORT_CMD in restored_dict else None
        return class_name, code_file_path, config_args, import_cmd, init_args, ref_type_args

    def size_in_bytes(self, file_pers_service: AbstractFilePersistenceService,
                      dict_pers_service: AbstractDictPersistenceService) -> int:
        result = 0

        # size of the dict
        result += dict_pers_service.dict_size(self.store_id, RESTORABLE_OBJECT)
        restored_dict = dict_pers_service.recover_dict(self.store_id, RESTORABLE_OBJECT)

        # size of all referenced files/objects
        if CODE_FILE in restored_dict:
            result += file_pers_service.file_size(restored_dict[CODE_FILE])

        result += file_pers_service.file_size(restored_dict[STATE_FILE])

        return result

    def restore_instance(self, ref_type_args: dict = None):
        if self.init_ref_type_args or ref_type_args:
            assert self.init_ref_type_args and ref_type_args, self._generate_non_matching_parameter_message(
                ref_type_args)
            keys = set(ref_type_args.keys())
            assert keys == set(self.init_ref_type_args), self._generate_non_matching_parameter_message(
                ref_type_args)

        init_args = self.init_args
        if len(self.config_args) > 0:
            add_params_from_config(init_args, self.config_args)

        self.instance = create_object_with_parameters(
            code=self.code, import_cmd=self.import_cmd, class_name=self.class_name, init_args=init_args,
            init_ref_type_args=ref_type_args)

    def _generate_non_matching_parameter_message(self, ref_type_args):
        return 'given parameters not match the expected parameters - expected: {}, given: {}'.format(
            self.init_ref_type_args, ref_type_args)

    def _representation_type(self) -> str:
        return RESTORABLE_OBJECT


class StateDictObj(metaclass=abc.ABCMeta):
    def __init__(self):
        self.state_objs: Dict[str, RestorableObjectWrapper] = {}


class StateDictRestorableObjectWrapper(AbstractRestorableObjectWrapper):

    def __init__(self, class_name: str, code: str, instance: StateDictObj = None, store_id: str = None):
        super().__init__(class_name, code, instance, store_id)
        self.instance: StateDictObj = instance

    def _persist_class_specific_fields(self, dict_representation, file_pers_service, dict_pers_service):
        super()._persist_class_specific_fields(dict_representation, file_pers_service, dict_pers_service)

        # persist instance state dict
        state_dict_refs = {}
        for k, v in self.instance.state_objs.items():
            obj: RestorableObjectWrapper = v
            obj_id = obj.persist(file_pers_service, dict_pers_service)
            state_dict_refs[k] = obj_id

        dict_representation[STATE_DICT] = state_dict_refs

    @classmethod
    def load(cls, obj_id: str, file_pers_service: AbstractFilePersistenceService,
             dict_pers_service: AbstractDictPersistenceService, restore_root: str):
        restored_dict = dict_pers_service.recover_dict(obj_id, RESTORABLE_OBJECT)

        class_name = restored_dict[CLASS_NAME]
        code_file_path = file_pers_service.recover_file(restored_dict[CODE_FILE], restore_root)

        restorable_obj_wrapper = cls(store_id=obj_id, code=code_file_path, class_name=class_name)

        return restorable_obj_wrapper

    @abc.abstractmethod
    def restore_instance(self, file_pers_service: AbstractFilePersistenceService,
                         dict_pers_service: AbstractDictPersistenceService, restore_root: str):
        raise NotImplementedError

    def size_in_bytes(self, file_pers_service: AbstractFilePersistenceService,
                      dict_pers_service: AbstractDictPersistenceService) -> int:
        # TODO implement
        return 0

    def _representation_type(self) -> str:
        return RESTORABLE_OBJECT


class StateFileRestorableObjectWrapper(RestorableObjectWrapper):
    def __init__(self, class_name: str, init_args: dict, init_ref_type_args: [str], config_args: dict, code: str = None,
                 import_cmd: str = None, instance: object = None, store_id: str = None, state_file: str = None):
        super().__init__(class_name, init_args, init_ref_type_args, config_args, code, import_cmd, instance, store_id)
        self.state_file = state_file

    def persist(self, file_pers_service: AbstractFilePersistenceService,
                dict_pers_service: AbstractDictPersistenceService) -> str:

        # the state of the instance has probably changed -> need to store new version with new id
        self.store_id = dict_pers_service.generate_id()

        dict_representation = super()._persist_fields(dict_pers_service, file_pers_service)

        if self.instance:
            with tempfile.TemporaryDirectory() as tmp_path:
                state_file = os.path.join(tmp_path, 'state')
                self._save_instance_state(state_file)
                state_file_id = file_pers_service.save_file(state_file)

            dict_representation[STATE_FILE] = state_file_id

        dict_pers_service.save_dict(dict_representation, RESTORABLE_OBJECT)

        return self.store_id

    def _add_optional_fields(self, dict_representation, file_pers_service, dict_pers_service):
        super(StateFileRestorableObjectWrapper, self)._add_optional_fields(dict_representation, file_pers_service,
                                                                           dict_pers_service)

        if self.state_file:
            state_file_id = file_pers_service.save_file(self.state_file)
            dict_representation[STATE_FILE] = state_file_id

    @classmethod
    def load(cls, obj_id: str, file_pers_service: AbstractFilePersistenceService,
             dict_pers_service: AbstractDictPersistenceService, restore_root: str):
        restored_dict = dict_pers_service.recover_dict(obj_id, RESTORABLE_OBJECT)

        class_name, code_file_path, config_args, import_cmd, init_args, ref_type_args = \
            RestorableObjectWrapper._restore_fields(file_pers_service, restore_root, restored_dict)

        state_file = None
        if STATE_FILE in restored_dict:
            state_file_id = restored_dict[STATE_FILE]
            state_file = file_pers_service.recover_file(state_file_id, restore_root)

        obj = cls(store_id=obj_id, class_name=class_name, code=code_file_path, config_args=config_args,
                  import_cmd=import_cmd, init_args=init_args, init_ref_type_args=ref_type_args, state_file=state_file)

        return obj

    def restore_instance(self, ref_type_args: dict = None):
        super(StateFileRestorableObjectWrapper, self).restore_instance(ref_type_args)

        if self.state_file:
            self._restore_instance_state(self.state_file)

    @abc.abstractmethod
    def _save_instance_state(self, path):
        """
        Saves the state of the internal instance to a file. Only needs to be implemented when there is a internal state
        that can not be reproduced by passing the right arguments in the constructor.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def _restore_instance_state(self, path):
        """
        Loads the state for the internal instance from a file.
        """
        raise NotImplementedError


class TrainService(StateDictObj):

    @abc.abstractmethod
    def train(self, model: torch.nn.Module):
        raise NotImplementedError


def add_params_from_config(init_args, config_args):
    config_file = os.getenv(MMLIB_CONFIG)
    config = configparser.ConfigParser()
    config.read(config_file)

    for k, v in config_args.items():
        init_args[k] = config[VALUES][v]


class OptimizerWrapper(StateFileRestorableObjectWrapper):

    def _save_instance_state(self, path):
        if self.instance:
            state_dict = self.instance.state_dict()
            torch.save(state_dict, path)

    def _restore_instance_state(self, path):
        self.instance.load_state_dict(torch.load(path))
