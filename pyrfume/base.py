import configparser
import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
import pickle
from pprint import pprint
import requests
import tempfile
import toml
from tqdm.auto import tqdm, trange
from typing import Any
import urllib


PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_DIR / "config.ini"
DEFAULT_DATA_PATH = PACKAGE_DIR.parent / "data"
REMOTE_DATA_ORG = 'pyrfume'
REMOTE_DATA_REPO = 'pyrfume-data'
REMOTE_DATA_PATH = 'https://raw.githubusercontent.com/%s/%s' % (REMOTE_DATA_ORG, REMOTE_DATA_REPO)
TEMP_LOCAL = tempfile.TemporaryDirectory()
MANIFEST_NAME = 'manifest.toml'


class LocalDataError(Exception):
    pass


class RemoteDataError(Exception):
    pass


logger = logging.getLogger("pyrfume")


def init_config(overwrite=False):
    if overwrite or not CONFIG_PATH.exists():
        config = configparser.ConfigParser()
        config["PATHS"] = {"pyrfume-data": str(DEFAULT_DATA_PATH)}
        config["DATABASE"] = {"schema_name": "UNDEFINED"}
        with open(CONFIG_PATH, "w") as f:
            config.write(f)


def reset_config():
    init_config(overwrite=True)


def read_config(header, key):
    config = configparser.ConfigParser()
    init_config()
    config.read(CONFIG_PATH)
    return config[header][key]


def write_config(header, key, value):
    config = configparser.ConfigParser()
    init_config()
    config.read(CONFIG_PATH)
    config[header][key] = value
    with open(CONFIG_PATH, "w") as f:
        config.write(f)


def set_data_path(path):
    path = Path(path).resolve()
    if not path.exists():
        raise Exception("Could not find path %s" % path)
    write_config("PATHS", "pyrfume-data", str(path))


def get_data_path():
    path = read_config("PATHS", "pyrfume-data")
    path = Path(path).resolve()
    if not path.exists():
        raise Exception("Could not find data path %s" % path)
    return path


def get_remote_data_path(branch='master'):
    path = REMOTE_DATA_PATH + '/' + branch
    return path


def localize_remote_data(rel_path, branch='master'):
    url = get_remote_data_path(branch=branch) + '/' + rel_path
    target_path = Path(TEMP_LOCAL.name) / rel_path
    response = requests.get(url)
    if response.status_code != 200:
        raise RemoteDataError('Could not get file at %s' % url)
    target_path.parent.mkdir(exist_ok=True)
    with open(target_path, 'wb') as f:
        f.write(response.content)
    return target_path
    
def get_remote_archives_info(branch='master'):
    url = 'https://api.github.com/repos/%s/%s/git/trees/%s' % (REMOTE_DATA_ORG, REMOTE_DATA_REPO, branch)
    response = requests.get(url)
    if response.status_code != 200:
        raise RemoteDataError('Could not get archive list at %s' % url)
    info = json.loads(response.content)
    return info

    
def list_archives(branch='master', remote=None):
    archives = []
    if remote:
        info = get_remote_archives_info(branch=branch)
        for item in info['tree']:
            if item['type'] == 'tree':
                archives.append(item['path'])    
    else:
        path = get_data_path()
        for directory in path.iterdir():
            if (directory / 'manifest.toml').is_file():
                archives.append(directory.name)
        if not len(archives):
            f = logger.info if remote is None else logger.warning
            f('No local archives found; searching remotely...')
            return list_archives(branch=branch, remote=True)
    archives = sorted(archives)
    return archives
    
    
def load_manifest(archive_name, remote=None):
    rel_path = archive_name + '/' + MANIFEST_NAME 
    return load_data(rel_path, remote=remote)


def show_files(archive_name, remote=None, raw=False):
    manifest = load_manifest(archive_name, remote=remote)
    items = manifest['processed']
    if raw:
        items.update(manifest['raw'])
    pprint(items)
    
    
def load_data(rel_path, remote=None, **kwargs):
    if remote:
        full_path = localize_remote_data(rel_path)
    else:
        full_path = get_data_path() / rel_path
        if not full_path.exists():
            if remote is None:
                logger.info('Did not find file %s locally; fetching remotely.' % full_path)
                return load_data(rel_path, remote=True, **kwargs)
            else:
                raise LocalDataError('Could not get file at %s' % full_path)
      
    is_csv = full_path.suffix in [".csv", ".txt"]
    is_pickle = full_path.suffix in [".pkl", ".pickle", ".p"]
    is_excel = full_path.suffix in  [".xls", ".xlsx"]
    is_manifest = full_path.suffix == Path(MANIFEST_NAME).suffix
    
    if is_pickle:
        with open(full_path, "rb") as f:
            data = pickle.load(f)
    elif is_excel:
        data = pd.read_excel(full_path, **kwargs)
    elif is_csv:
        if "index_col" not in kwargs:
            kwargs["index_col"] = 0
        data = pd.read_csv(full_path, **kwargs)
    elif is_manifest:
        with open(full_path, 'r') as f:
            data = toml.load(f)
    else:
        raise LocalDataError("%s has an unknown data type" % rel_path)
    return data


def save_data(data, rel_path, **kwargs):
    full_path = get_data_path() / rel_path
    is_pickle = any(str(full_path).endswith(x) for x in (".pkl", ".pickle", ".p"))
    is_csv = any(str(full_path).endswith(x) for x in (".csv"))
    if is_pickle:
        with open(full_path, "wb") as f:
            pickle.dump(data, f)
    elif is_csv:
        data.to_csv(full_path, **kwargs)
    else:
        raise Exception("Unsupported extension in file name %s" % full_path.name)