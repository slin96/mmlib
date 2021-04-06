import locale
import platform
import subprocess

import torch
from torch.utils.collect_env import get_pretty_env_info

from schema.environment import Environment


def get_python_platform_info():
    python_env_dict = {
        'architecture': platform.architecture(),
        'machine': platform.machine(),
        'node': platform.node(),
        'platform': platform.platform(),
        'processor': platform.processor(),
        'python_build': platform.python_build(),
        'python_compiler': platform.python_compiler(),
        'python_branch': platform.python_branch(),
        'python_implementation': platform.python_implementation(),
        'python revision': platform.python_revision(),
        'python_version': platform.python_version(),
        'python_version_tuple': platform.python_version_tuple(),
        'release': platform.release(),
        'system': platform.system(),
        'version': platform.version(),
        'uname': platform.uname(),
        'mac_ver': platform.mac_ver(),
        'libc_ver': platform.libc_ver()
    }

    return python_env_dict


def get_python_libs():
    output: str = _run('pip freeze')[1]
    installed = output.split('\n')
    return installed


def _run(command):
    # copied from torch.utils.collect_env
    """Returns (return-code, stdout, stderr)"""
    p = subprocess.Popen(command, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, shell=True)
    raw_output, raw_err = p.communicate()
    rc = p.returncode
    enc = locale.getpreferredencoding()
    output = raw_output.decode(enc)
    err = raw_err.decode(enc)
    return rc, output.strip(), err.strip()


def get_pytorch_env():
    return torch.utils.collect_env.get_env_info()


def track_current_environment() -> Environment:
    raise NotImplementedError


if __name__ == '__main__':
    get_pytorch_env()
