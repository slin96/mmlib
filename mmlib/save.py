import abc
import os
import shutil
import sys
import zipfile
from enum import Enum
from shutil import copyfile

import bson
import torch

from mmlib.persistence import AbstractPersistenceService
from util.helper import zip_dir

SAVE_PATH = 'save-path'
SAVE_TYPE = 'save-type'
NAME = 'name'
MODELS = 'models'

ID = '_id'

MODEL_INFO = 'model_info'
RECOVER_T1 = 'recover_t1'


class SaveType(Enum):
    PICKLED_MODEL = 1
    ARCHITECTURE_AND_WEIGHTS = 2
    PROVENANCE = 3


class RecoverInfoT1(Enum):
    PICKLED_MODEL = 'pickled_model'
    MODEL_CODE = 'model_code'
    GENERATE_CALL = 'generate_call'
    RECOVER_VAL = 'recover_val'


class ModelInfo(Enum):
    NAME = 'name'
    STORE_TYPE = 'store_type'
    RECOVER_INFO = 'recover_info'
    DERIVED_FROM = 'derived_from'
    INFERENCE_INFO = 'inference_info'
    TRAIN_INFO = 'train_info'


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
                hasattr(subclass, 'saved_model_ids') and
                callable(subclass.saved_model_ids) or
                NotImplemented)

    @abc.abstractmethod
    def save_model(self, name: str, generate_call: str, model: torch.nn.Module, code: str, import_root: str) -> str:
        """
        Saves a model as a pickle dump together with the given metadata.
        :param generate_call: TODO docs
        :param name: The name of the model as a string. Used for easier identification.
        :param model: The model object.
        :param code: The path to the code of the model (is needed for recover process)
        :param import_root: The directory that is root for all imports, e.g. the Python project root.
        :return: Returns the ID that was used to store the model data in the MongoDB.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def save_version(self, model: torch.nn.Module, base_model_id: str) -> str:
        """
        Saves a new model version by referring to the base_model
        :param model: The model to save.
        :param base_model_id: the model id of the base_model
        :return: Returns the ID that was used to store the new model version data in the MongoDB.
        """

    @abc.abstractmethod
    def saved_model_ids(self) -> [str]:
        """Returns list of saved models ids"""
        raise NotImplementedError

    @abc.abstractmethod
    def model_save_size(self, model_id: str) -> float:
        """
        Calculates and returns the amount of bytes that are used for storing the model.
        :param model_id: The ID to identify the model in the mongoDB.
        :return: The amout of bytes used to store the model.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def recover_model(self, model_id: str) -> torch.nn.Module:
        """
        Recovers a the model identified by the given id.
        :param model_id: The id to identify the model with.
        :return: The recovered model as an object.
        """


class SimpleSaveRecoverService(AbstractSaveRecoverService):
    """TODO docs A Service that offers functionality to store PyTorch models. In order to do so it stores the metadata is
    stored in a MongoDB, the model (pickled) is stored on the file system. """

    def __init__(self, persistence_service: AbstractPersistenceService, tmp_path: str):
        """
        TODO docs
        :param base_path: The path that is used as a root directory for everything that is stored to the file system.
        :param host: The host name or Ip address to connect to a running MongoDB instance.
        """
        self._pers_service = persistence_service
        self._tmp_path = tmp_path

    def save_model(self, name: str, generate_call: str, model: torch.nn.Module, code: str, import_root: str) -> str:
        dst_path = os.path.join(self._tmp_path, self._pers_service.generate_id())

        zip_file = self._pickle_model(model, code, import_root, dst_path)
        zip_file_id = self._pers_service.save_file(zip_file)
        code_file_id = self._pers_service.save_file(code)

        self._clean(dst_path)
        self._clean(zip_file)

        recover_info_t1 = {
            RecoverInfoT1.PICKLED_MODEL.value: zip_file_id,
            RecoverInfoT1.MODEL_CODE.value: code_file_id,
            RecoverInfoT1.GENERATE_CALL.value: generate_call,
            RecoverInfoT1.RECOVER_VAL.value: None  # TODO to implement
        }
        recover_info_id = self._pers_service.save_dict(recover_info_t1, RECOVER_T1)

        model_dict = {
            ModelInfo.NAME.value: name,
            ModelInfo.STORE_TYPE.value: SaveType.PICKLED_MODEL.value,
            ModelInfo.RECOVER_INFO.value: recover_info_id,
            ModelInfo.DERIVED_FROM.value: None,  # TODO to implement
            ModelInfo.INFERENCE_INFO.value: None,  # TODO to implement
            ModelInfo.TRAIN_INFO.value: None  # TODO to implement

        }
        model_id = self._pers_service.save_dict(model_dict, MODEL_INFO)

        return model_id

    def save_version(self, model: torch.nn.Module, base_model_id: str) -> str:
        pass

    #     base_model_dict = self._get_model_dict(base_model_id)
    #     version_model_dict = base_model_dict.copy()
    #     base_model_save_path = base_model_dict[SAVE_PATH]
    #
    #     # save metadata to mongoDB
    #     # del fields that will change
    #     version_model_dict.pop(ID)
    #     version_model_dict.pop(SAVE_PATH)
    #     # add save path
    #     model_id = self._mongo_service.save_dict(version_model_dict)
    #     save_path = self._save_path(model_id)
    #     self._add_save_path(model_id, save_path)
    #
    #     # extract code and import root from base model
    #     code = self._code_path(base_model_save_path)
    #     import_root = os.path.splitext(base_model_save_path)[0]
    #
    #     self._pickle_model(model, code, import_root, os.path.join(self._base_path, str(model_id)))
    #
    #     return str(model_id)

    def saved_model_ids(self) -> [str]:
        pass
        # str_ids = list(map(str, self._mongo_service.get_ids()))
        # return str_ids

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
        pass
        # model_dict = self._get_model_dict(model_id)
        # return self._recover_model(model_dict)

    def _get_model_dict(self, model_id):
        model_id = bson.ObjectId(model_id)
        model_dict = self._mongo_service.get_dict(model_id)
        return model_dict

    def _recover_model(self, model_dict):
        save_type = SaveType(model_dict[SAVE_TYPE])
        if save_type == SaveType.PICKLED_MODEL:
            return self._recovered_pickled_model(model_dict)

    def _recovered_pickled_model(self, model_dict):
        file_path = model_dict[SAVE_PATH]

        unpacked_path = self._unzip(file_path)
        # make available for imports
        sys.path.append(unpacked_path)

        pickle_path = os.path.join(unpacked_path, 'model')
        loaded_model = torch.load(pickle_path)
        return loaded_model

    def _unzip(self, file_path):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(self._base_path)

        # remove .zip file ending
        unpacked_path = file_path.split('.')[0]

        return unpacked_path

    def _find_py_files(self, root):
        result = []
        for root, dirs, files in os.walk(root):
            for file in files:
                if file.endswith(".py"):
                    result.append(os.path.join(root, file))

        return result

    def _code_path(self, base_model_save_path):
        unzipped_root = self._unzip(base_model_save_path)
        # there should be only one file with ending ".py" and this should be the model
        py_files = self._find_py_files(unzipped_root)
        assert len(py_files) == 1
        code = py_files[0]
        return code

    def _pickle_model(self, model, code, import_root, save_path):
        # create directory to store in
        abs_save_path = os.path.abspath(save_path)
        os.makedirs(abs_save_path)

        # store pickle dump of model
        torch.save(model, os.path.join(abs_save_path, 'model'))

        # store code
        self._store_code(abs_save_path, code, import_root)

        # zip everything
        return self._zip(save_path)

    def _store_code(self, abs_save_path, code, import_root):
        code_abs_path = os.path.abspath(code)
        import_root_abs = os.path.abspath(import_root)
        copy_path, code_file = os.path.split(os.path.relpath(code_abs_path, import_root_abs))
        net_code_dst = os.path.join(abs_save_path, copy_path)
        # create dir structure in tmp file, needed to restore the pickle dump
        os.makedirs(net_code_dst)
        copyfile(code_abs_path, os.path.join(net_code_dst, code_file))

    def _zip(self, save_path):
        path, name = os.path.split(save_path)
        # temporarily change dict for zip process
        owd = os.getcwd()
        os.chdir(path)
        zip_name = name + '.zip'
        zip_dir(name, zip_name)
        # change path back
        os.chdir(owd)

        return os.path.join(path, zip_name)

    def _add_save_path(self, model_id, save_path):
        attribute = {SAVE_PATH: save_path}
        self._mongo_service.add_attribute(model_id, attribute)

    def _clean(self, path):
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
