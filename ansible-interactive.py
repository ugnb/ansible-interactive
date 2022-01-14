#!/usr/bin/env python3

import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Optional, Tuple

ANSIBLE_HOSTS_LOCATION = "/etc/ansible/hosts"

IMPORT_PATTERN = re.compile("^-\s+import_playbook[:\s]+(.+)$", re.M)
PLAY_NAME_PATTERN = re.compile("^-\s+name[:\s]+(.+)$", re.M)
VARIABLES_PATTERN = re.compile("{{\s*([^}\s]+)", re.M)
HOST_FILE_ENTRY_PATTERN = re.compile("^([^\s]+)")


def print_new_line():
    print(os.linesep)


def ask(question: str) -> bool:
    choice = input("{}? (y/n) ".format(question))
    return choice.lower() == "y" 


def propose_options(caption: str, options: list[str], propose_all = False, allow_none = False) -> Optional[str]:
    if propose_all:
        print("{}. {}".format(0, "All"))
    for i, option in enumerate(options):
        print("{}. {}".format(i + 1, option))
    while True:
        choice = input("Choose {}{}: ".format(caption, " or press 'Enter' to continue" if allow_none else ""))
        try:
            if allow_none and not len(choice):
                return None
            number = int(choice.strip())
        except ValueError:
            print("Invalid choice")
            continue

        if number < 0 or (not propose_all and number == 0) or number > len(options):
            print("Invalid choice")
            continue

        return options[number - 1]


def propose_multiple_options(caption: str, options: list[str]) -> list[str]:
    print("{}. {}".format(0, "All"))
    for i, option in enumerate(options):
        print("{}. {}".format(i + 1, option))
    while True:
        choice = input("Choose {}: ".format(caption))
        try:
            numbers = [int(number.strip()) for number in choice.split(",") if number]
        except ValueError:
            print("Invalid choice")
            continue

        for number in numbers:
            if number < 0 or number > len(options):
                print("Invalid choice")
                continue

        if (0 in numbers):
            return options

        result = [options[option - 1] for option in numbers]
        result.sort()
        return result


def ask_for_hosts_file(ansible_hosts_file: str) -> str:
    ansible_hosts_file = input("Enter correct location: ")
    while not os.path.isfile(ansible_hosts_file):
        ansible_hosts_file = input("File '{}' does not exist.{}Enter correct location: ".format(ansible_hosts_file, os.linesep))
    
    return ansible_hosts_file


def check_hosts_file(ansible_hosts_file: str) -> str:
    if not os.path.isfile(ansible_hosts_file):
        print("Default file '{}' does not exist.".format(ansible_hosts_file))
        ansible_hosts_file = ask_for_hosts_file(ansible_hosts_file)

    if not ask("Ansible hosts file location is '{}'.{}Is that correct".format(ANSIBLE_HOSTS_LOCATION, os.linesep)):
        ansible_hosts_file = ask_for_hosts_file(ansible_hosts_file)

    print_new_line()
    return ansible_hosts_file


def select_playbook(path_to_playbooks: str) -> Tuple[str, str]:
    yaml_files = Path(path_to_playbooks).rglob('*.yml')

    found_playbooks = {path.name: path.absolute() for path in yaml_files}

    selected_playbook_name = propose_options("playbook", sorted(list(found_playbooks.keys())))
    selected_playbook_path = found_playbooks[selected_playbook_name]

    with open(selected_playbook_path) as f:
        yaml_string = f.read()
    
    print_new_line()
    return selected_playbook_path, yaml_string


def find_plays_in_playbook(selected_playbook_path: str, yaml_string: str) -> list[str]:
    plays = re.findall(PLAY_NAME_PATTERN, yaml_string)
    imports = re.findall(IMPORT_PATTERN, yaml_string)

    for imported_playbook in imports:
        imported_playbook_path = os.path.join(os.path.dirname(selected_playbook_path), imported_playbook)

        if not os.path.isfile(imported_playbook_path):
            print("Warning: incorrect import in '{}': '{}'".format(selected_playbook_path, imported_playbook))
            continue

        with open(imported_playbook_path) as f:
            imported_playbook_yaml_string = f.read()
            plays += find_plays_in_playbook(imported_playbook_path, imported_playbook_yaml_string)

    return plays


def print_playbook_info(playbook_path: str, yaml_string: str):
    playbook_plays = find_plays_in_playbook(playbook_path, yaml_string)
    print("Following plays are defined in playbook:")
    print(os.linesep.join(playbook_plays))
    print_new_line()


def find_variables_in_playbook(yaml_string: str) -> list[str]:
    variables = list(set(re.findall(VARIABLES_PATTERN, yaml_string)))
    variables.sort()
    return variables


def select_hosts_and_groups(ansible_hosts_file: str) -> Tuple[list[str], list[str]]:
    with open(ansible_hosts_file) as f:
        ansible_hosts_entries = []
        for line in f:
            matches = re.search(HOST_FILE_ENTRY_PATTERN, line)
            if matches:
                ansible_hosts_entries.append(matches.group(1))

    selected_hosts_entries = propose_multiple_options("multiple hosts or groups (comma-separated)", ansible_hosts_entries)

    groups = []
    hosts = []

    for hosts_entry in selected_hosts_entries:
        if hosts_entry.startswith("["):
            groups.append(hosts_entry[1:-1])
        else:
            hosts.append(hosts_entry)

    print_new_line()
    return groups, hosts


def define_variables_values(variables: list[str]) -> dict[str, str]:
    defined_variables = {}
    if ask("Want to define variables"):
        while True:
            chosen_var = propose_options("variable", variables, False, True)
            if not chosen_var:
                break
            defined_variables[chosen_var] = input("Value: ")
            print_new_line()
    
    return defined_variables


def build_ansible_command(selected_playbook_path: str, defined_variables: dict[str, str], groups_and_hosts: list[str]):
    command = ["ansible-playbook", str(selected_playbook_path)]

    for k, v in defined_variables.items():
        command.append("--extra-vars")
        command.append("{}={}".format(k, v))

    command += ["--limit", ":".join(groups_and_hosts)]

    if ask("Ask for SSH password"):
        command += ["--ask-pass"]

    if ask("Ask for privilege escalation password"):
        command += ["--ask-become-pass"]

    return command


def execute_command(command: list[str]) -> int:
    print("Going to execute following command: ")
    print(" ".join(command))
    if ask("Proceed"):
        try:
            return subprocess.run(command).returncode
        except Exception as e:
            print("Failed to execute ansible playbook: {}".format(e))
            return 1
    return 0


if __name__ == '__main__':
    if len(sys.argv) > 1:
        path_to_playbooks = sys.argv[1]
        if not os.path.exists(path_to_playbooks):
            print("Invalid path to playbooks directory")
    else:
        path_to_playbooks = os.getcwd()
    try:
        ANSIBLE_HOSTS_LOCATION = check_hosts_file(ANSIBLE_HOSTS_LOCATION)
        playbook_path, yaml_string = select_playbook(path_to_playbooks)
        print_playbook_info(playbook_path, yaml_string)
        groups, hosts = select_hosts_and_groups(ANSIBLE_HOSTS_LOCATION)
        variables = find_variables_in_playbook(yaml_string)
        defined_variables = define_variables_values(variables)
        command = build_ansible_command(playbook_path, defined_variables, groups + hosts)
        sys.exit(execute_command(command))
    except KeyboardInterrupt as interrupt:
        print(os.linesep)
        sys.exit(130)
