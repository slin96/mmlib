import abc
import os
import sys
from enum import Enum

import torch

from mmlib.persistence import AbstractPersistenceService
from mmlib.schema.model_info import ModelInfo
from mmlib.schema.recover_info_t1 import RecoverInfoT1
from mmlib.schema.schema_obj import SchemaObjType
from util.helper import clean
from util.zip import zip_path, unzip

ID = '_id'
MODEL_WEIGHTS = 'model_weights'
TMP_DIR = 'tmp-dir'
NAME = 'name'
MODELS = 'models'


class SaveType(Enum):
    PICKLED_WEIGHTS = 1
    WEIGHT_UPDATES = 2
    PROVENANCE = 3


# TODO if for experiments Python 3.8 is available, use protocol here
class AbstractSaveRecoverService(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'save_model') and
                callable(subclass.save_model) and
                hasattr(subclass, 'save_version') and
                callable(subclass.save_version) and
                hasattr(subclass, 'recover_model') and
                callable(subclass.recover_model) and
                hasattr(subclass, 'saved_model_infos') and
                callable(subclass.saved_model_infos) and
                hasattr(subclass, 'saved_model_ids') and
                callable(subclass.saved_model_ids) or
                NotImplemented)

    @abc.abstractmethod
    def save_model(self, model: torch.nn.Module, code: str, code_name: str, ) -> str:
        """
        Saves a model together with the given metadata.
        :param model: The actual model to save as an instance of torch.nn.Module.
        :param code: The path to the code of the model (is needed for recover process).
        :param code_name: The name of the model, i.e. the model constructor (is needed for recover process).
        :return: Returns the id that was used to store the model.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def save_version(self, model: torch.nn.Module, base_model_id: str) -> str:
        """
        Saves a new model version by referring to the base_model.
        :param model: The actual model to save as an instance of torch.nn.Module.
        :param base_model_id: the model id of the base_model.
        :return: Returns the ID that was used to store the new model version data in the MongoDB.
        """

    @abc.abstractmethod
    def saved_model_ids(self) -> [str]:
        """Returns list of saved models ids"""
        raise NotImplementedError

    @abc.abstractmethod
    def saved_model_infos(self) -> [dict]:
        """Returns list of saved models infos"""
        raise NotImplementedError

    @abc.abstractmethod
    def recover_model(self, model_id: str) -> torch.nn.Module:
        """
        Recovers a the model identified by the given model id.
        :param model_id: The id to identify the model with.
        :return: The recovered model as an object of type torch.nn.Module.
        """

    @abc.abstractmethod
    def model_save_size(self, model_id: str) -> float:
        """
        Calculates and returns the amount of bytes that are used for storing the model.
        :param model_id: The id to identify the model.
        :return: The amount of bytes used to store the model.
        """
        raise NotImplementedError


class SimpleSaveRecoverService(AbstractSaveRecoverService):
    """A Service that offers functionality to store PyTorch models by making use of a persistence service.
     The metadata is stored in JSON like dictionaries, files and weights are stored as files."""

    def __init__(self, persistence_service: AbstractPersistenceService, tmp_path: str):
        """
        :param persistence_service: An instance of AbstractPersistenceService that is used to store metadata and files.
        :param tmp_path: A path/directory that can be used to store files temporarily.
        """
        self._pers_service = persistence_service
        self._tmp_path = os.path.abspath(tmp_path)

    def save_model(self, model: torch.nn.Module, code: str, code_name: str, ) -> str:
        recover_info_t1 = self._save_model_t1(model, code, code_name)
        recover_info_id = self._pers_service.save_dict(recover_info_t1.to_dict(), SchemaObjType.RECOVER_T1.value)

        # TODO to implement other fields that are default None
        model_id = self._save_model_info(SaveType.PICKLED_WEIGHTS.value, recover_info_id)

        return model_id

    def _save_model_info(self, store_type, recover_info_id, derived_from=None, inference_info=None, train_info=None):
        model_info = ModelInfo(store_type=store_type, recover_info=recover_info_id, derived_from=derived_from,
                               inference_info=inference_info, train_info=train_info)
        model_id = self._pers_service.save_dict(model_info.to_dict(), SchemaObjType.MODEL_INFO.value)
        return model_id

    def _save_model_t1(self, model, code, code_name):
        gen_id = self._pers_service.generate_id()
        dst_path = os.path.join(self._tmp_path, gen_id)

        zip_file = self._pickle_weights(model, dst_path)
        zip_file_id = self._pers_service.save_file(zip_file)
        code_file_id = self._pers_service.save_file(code)
        clean(dst_path)
        clean(zip_file)

        recover_info_t1 = RecoverInfoT1(r_id=gen_id, weights=zip_file_id, model_code=code_file_id, code_name=code_name)

        return recover_info_t1

    def save_version(self, model: torch.nn.Module, base_model_id: str) -> str:
        base_model_info = self._get_model_info(base_model_id)
        base_model_recover_info = self._get_recover_info_t1(base_model_info)

        # copy fields from previous model that will stay the same
        code_name = base_model_recover_info.code_name

        tmp_path = os.path.abspath(os.path.join(self._tmp_path, TMP_DIR))
        os.mkdir(tmp_path)  # TODO maybe use with context
        code = self._pers_service.recover_file(base_model_recover_info.model_code, tmp_path)

        recover_info_t1 = self._save_model_t1(model, code, code_name)
        clean(tmp_path)

        recover_info_id = self._pers_service.save_dict(recover_info_t1.to_dict(), SchemaObjType.RECOVER_T1.value)

        # TODO to implement other fields that are default None
        model_id = self._save_model_info(SaveType.PICKLED_WEIGHTS.value, recover_info_id, derived_from=base_model_id)

        return model_id

    def saved_model_ids(self) -> [str]:
        return self._pers_service.get_all_dict_ids(SchemaObjType.MODEL_INFO.value)

    def saved_model_infos(self) -> [dict]:
        model_ids = self.saved_model_ids()
        return [self._get_model_info(i) for i in model_ids]

    def model_save_size(self, model_id: str) -> float:
        pass
        # model_id = bson.ObjectId(model_id)
        #
        # document_size = self._mongo_service.document_size(model_id)
        #
        # meta_data = self._mongo_service.get_dict(model_id)
        # save_path = meta_data[SAVE_PATH]
        # zip_size = os.path.getsize(save_path)
        #
        # return document_size + zip_size

    def recover_model(self, model_id: str) -> torch.nn.Module:
        model_info = self._get_model_info(model_id)
        recover_info_t1 = self._get_recover_info_t1(model_info)
        weights_file_id = recover_info_t1.weights

        tmp_path = os.path.abspath(os.path.join(self._tmp_path, TMP_DIR))
        os.mkdir(tmp_path)  # TODO maybe use with context
        code_id = recover_info_t1.model_code
        code = self._pers_service.recover_file(code_id, tmp_path)
        generate_call = recover_info_t1.code_name
        model = self._init_model(code, generate_call)

        weights_file = self._pers_service.recover_file(weights_file_id, tmp_path)
        s_dict = self._recover_pickled_weights(weights_file, tmp_path)
        model.load_state_dict(s_dict)

        clean(tmp_path)

        return model

    def _get_model_info(self, model_id):
        model_info_dict = self._pers_service.recover_dict(model_id, SchemaObjType.MODEL_INFO.value)

        model_info = ModelInfo()
        model_info.load_dict(model_info_dict)

        return model_info

    def _get_recover_info_t1(self, model_info):
        recover_info_id = model_info.recover_info
        recover_info_dict = self._pers_service.recover_dict(recover_info_id, SchemaObjType.RECOVER_T1.value)

        recover_info = RecoverInfoT1()
        recover_info.load_dict(recover_info_dict)

        return recover_info

    def _pickle_weights(self, model, save_path):
        # create directory to store in
        abs_save_path = os.path.abspath(save_path)
        os.makedirs(abs_save_path)

        # store pickle dump of model
        torch.save(model.state_dict(), os.path.join(abs_save_path, MODEL_WEIGHTS))

        # zip everything
        return zip_path(save_path)

    def _recover_pickled_weights(self, weights_file, extract_path):
        unpacked_path = unzip(weights_file, extract_path)
        pickle_path = os.path.join(unpacked_path, MODEL_WEIGHTS)
        state_dict = torch.load(pickle_path)

        return state_dict

    def _init_model(self, code, generate_call):
        path, file = os.path.split(code)
        module = file.replace('.py', '')
        sys.path.append(path)
        exec('from {} import {}'.format(module, generate_call))
        model = eval('{}()'.format(generate_call))

        return model
