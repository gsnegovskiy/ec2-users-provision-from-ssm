#!/usr/bin/env python3

import os
import sys
import subprocess
import json
import boto3
import requests
from pathlib import Path
import shutil

instance_data = json.loads(requests.get('http://169.254.169.254/latest/dynamic/instance-identity/document').text)
REGION = instance_data['region']

SSM = boto3.client('ssm', region_name = REGION)

USERS_GROUP="ssm_users"

def remove_users(group_members):
    for user in group_members:
        userdel_comm = f"userdel {user}"
        subprocess.check_call(userdel_comm, stdout=sys.stdout, stderr=sys.stderr, cwd=None, shell=True)
        dirpath = Path(f"/home/{user}")
        if dirpath.exists() and dirpath.is_dir():
            shutil.rmtree(dirpath)

def group_provision():
    groupadd_comm = f"groupadd -f {USERS_GROUP}"
    subprocess.check_call(groupadd_comm, stdout=sys.stdout, stderr=sys.stderr, cwd=None, shell=True)

def user_list_check(username,group_members):
    group_members.index(username)

def get_group_members():
    #Output of getent will be like "ssm_users:x:1001:test,test2"
    group_members_comm = f"getent group {USERS_GROUP}"
    group_members_raw = subprocess.run(group_members_comm, stdout=subprocess.PIPE, shell=True).stdout.decode('utf-8').split(":")
    users_array = (group_members_raw[len(group_members_raw) - 1]).replace('\n', '').split(",")
    return users_array

def user_provision(username,ssh_pubkey):
    useradd_command = f"useradd -m -N -G {USERS_GROUP} {username}"
    try:
       subprocess.run(useradd_command, stdout=sys.stdout, stderr=sys.stderr, cwd=None, shell=True)
    except subprocess.CalledProcessError as e:
        if e.returncode == "9" :
            print("User is already here")
        else:
            print(f"Error code: {e}")
    ssh_folder = f"/home/{username}/.ssh/"
    auth_file = f"{ssh_folder}authorized_keys"
    Path(ssh_folder).mkdir(parents = True, exist_ok = True, mode = 0o0700)
    shutil.chown(ssh_folder, username, USERS_GROUP)
    if not os.path.exists(auth_file):
        os.mknod(auth_file, mode = 0o0600)
        shutil.chown(auth_file, username, USERS_GROUP)
    f = open(auth_file, "w")
    f.write(ssh_pubkey + "\n")
    f.close()

def get_param_path():
    INSTANCE_ID = (requests.get('http://169.254.169.254/latest/meta-data/instance-id')).text
    ec2 = boto3.resource('ec2', region_name = REGION)
    ec2instance = ec2.Instance(INSTANCE_ID)
    instancename = ''
    for tags in ec2instance.tags:
        if tags["Key"] == 'Name':
            instancename = tags["Value"]
    name_splited = instancename.split("-")
    ENV = name_splited[len(name_splited) - 1]
    path = (f"/il/{ENV}/{instancename}")
    return path

def get_parameters_by_path(next_token = None):
    params = {
        'Path': get_param_path(),
        'Recursive': True,
        'WithDecryption': True
    }
    if next_token is not None:
        params['NextToken'] = next_token
    return SSM.get_parameters_by_path(**params)

def parameters():
    next_token = None
    while True:
        response = get_parameters_by_path(next_token)
        parameters = response['Parameters']
        if len(parameters) == 0:
            break
        for parameter in parameters:
            yield parameter
        if 'NextToken' not in response:
            break
        next_token = response['NextToken']

def main():
    group_provision()
    group_members = get_group_members()
    for parameter in parameters():
        username = os.path.basename(parameter['Name'])
        ssh_pubkey = parameter['Value']
        user_provision(username,ssh_pubkey)
        try:
            group_members.remove(username)
        except ValueError:
             print( f"{username} not in a users list. it's fine. user might be new")
    remove_users(group_members)

if __name__ == "__main__":
    main()
