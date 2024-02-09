#!/usr/bin/env python3
#
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Copyright (C) 2024 Collabora Limited
# Author: Ricardo Cañuelo Navarro <ricardo.canuelo@collabora.com>


# How to use this (for now):
#
#        docker-compose run results_checker
#
# To specify a date from which to start looking for results:
#
#        docker-compose run results_checker --date=<date>
#
# where <date> is in YYYY-MM-DD format.
#
# You can specify a settings preset other than the default (from the
# default yaml settings file) with the --preset flag


import sys
from datetime import datetime, timedelta

import json
import yaml

import kernelci
import kernelci.api.models as models
from kernelci.legacy.cli import Args, Command, parse_opts
from base import Service

SERVICE_NAME = 'results_checker'


class Reporter():
    def __init__(self, logger, api, api_helper, template_dir=None):
        self.log = logger
        self._template_dir = template_dir
        self._api = api
        self._api_helper = api_helper

    def _create_test_case_report(self, node, parent=None):
        out_str_parts = []
        # if not parent:
        #     parent = self._api_helper.get_node(node.parent)
        out_str_parts.append(f"Test id: {node.id}")
        out_str_parts.append(f"Name: {node.name} - suite: {node.group}")
        out_str_parts.append(f"Date: {node.created}")
        out_str_parts.append(f"Result: {node.result}")
        if node.parent.artifacts:
            if 'lava_log' in node.parent.artifacts:
                out_str_parts.append(f"Log: {node.parent.artifacts['lava_log']}")
            else:
                out_str_parts.append("NO TEST LOG")
        else:
            out_str_parts.append("***** Parent has no artifacts? wtf")
        out_str_parts.append("Kernel:\n"
                             f"    tree: {node.data.kernel_revision.tree}\n"
                             f"    branch: {node.data.kernel_revision.branch}\n"
                             f"    commit: {node.data.kernel_revision.commit}\n"
                             f"    describe: {node.data.kernel_revision.describe}")
        out_str_parts.append(f"Platform: {node.parent.data.platform}")
        out_str_parts.append(f"Lava job id: {node.data.job_id}")
        return '\n'.join(out_str_parts)

    def _create_test_suite_report(self, node):
        out_str_parts = ['']
        out_str_parts.append(f"Test id: {node.id}")
        out_str_parts.append(f"Name: {node.name}")
        out_str_parts.append(f"Date: {node.created}")
        if 'lava_log' in node.artifacts:
            out_str_parts.append(f"Log: {node.artifacts['lava_log']}")
        else:
            out_str_parts.append("NO TEST LOG")
        out_str_parts.append("Kernel:\n"
                      f"    tree: {node.data.kernel_revision.tree}\n"
                      f"    branch: {node.data.kernel_revision.branch}\n"
                      f"    commit: {node.data.kernel_revision.commit}\n"
                      f"    describe: {node.data.kernel_revision.describe}")
        out_str_parts.append(f"Platform: {node.data.platform}")
        out_str_parts.append(f"Lava job id: {node.data.job_id}")

        test_cases = self._api.node.find({'parent': node.id})
        out_str_parts.append(f"Test cases: {len(test_cases)}")
        for test_case in test_cases:
            test_case_obj = self._api_helper.get_node_obj(test_case)
            test_case_obj.parent = node
            indent = ' ' * 8
            out_str_parts.append(f"Test case: {test_case_obj.name}")
            out_str_parts.append(f"{indent}Test id: {test_case_obj.id}")
            out_str_parts.append(f"{indent}Result: {test_case_obj.result}\n")
        return '\n'.join(out_str_parts)


    def _create_kbuild_report(self, node):
        out_str_parts = ['']
        out_str_parts.append(f"Kbuild id: {node.id}")
        out_str_parts.append(f"Name: {node.name}")
        out_str_parts.append(f"Date: {node.created}")
        out_str_parts.append("Kernel:\n"
                             f"    tree: {node.data.kernel_revision.tree}\n"
                             f"    branch: {node.data.kernel_revision.branch}\n"
                             f"    commit: {node.data.kernel_revision.commit}\n"
                             f"    describe: {node.data.kernel_revision.describe}")
        out_str_parts.append("Artifacts:\n"
                             f"    Build log: {node.artifacts.get('build_log')}\n"
                             f"    Build image stdout: {node.artifacts.get('build_kimage_stdout')}\n"
                             f"    Build image errors: {node.artifacts.get('build_kernel_errors')}\n"
                             f"    Build modules stdout: {node.artifacts.get('build_modules_stdout')}\n"
                             f"    Build modules errors: {node.artifacts.get('build_modules_errors')}\n"
                             f"    Metadata: {node.artifacts.get('metadata')}\n"
                             f"    Kernel image: {node.artifacts.get('kernel')}\n"
                             f"    Kernel modules: {node.artifacts.get('modules')}")
        out_str_parts.append(f"Runtime: {node.data.runtime}")
        out_str_parts.append(f"Job id: {node.data.job_id}")
        return '\n'.join(out_str_parts)

    def _create_regression_report(self, node):
        out_str_parts = ['']
        node.data.pass_node = self._api_helper.get_node_obj(node.data.pass_node, True)
        node.data.fail_node = self._api_helper.get_node_obj(node.data.fail_node, True)
        out_str_parts.append(f"Name: {node.name} - suite: {node.group}")
        out_str_parts.append(f"Date: {node.created}")
        out_str_parts.append(f"Result: {node.result}")
        out_str_parts.append(f"Passed node: ...")
        out_str_parts.append(self.create_report(node.data.pass_node))
        out_str_parts.append(f"Failed node: ...")
        out_str_parts.append(self.create_report(node.data.fail_node))
        return '\n'.join(out_str_parts)

    def create_report(self, node, parent=None):
        if node.kind == 'test':
            if node.is_test_suite():
                report = self._create_test_suite_report(node)
            else:
                report = self._create_test_case_report(node, parent)
        elif node.kind == 'kbuild':
            report = self._create_kbuild_report(node)
        elif node.kind == 'regression':
            report = self._create_regression_report(node)
        else:
            raise NotImplementedError("Settings type not implemented")
        return ("============================================================\n"
                f"{report}\n"
                "============================================================\n")


class ResultsChecker(Service):
    def __init__(self, configs, args):
        super().__init__(configs, args, SERVICE_NAME)
        with open(args.config, 'r') as settings_file:
            self._settings = yaml.safe_load(settings_file)
        self.log.info(f"[ResultsChecker init] settings: {self._settings}")
        if args.preset:
            self._preset_name = args.preset
        else:
            self._preset_name = 'default'
        if self._preset_name not in self._settings:
            self.log.error(f"No {self._preset_name} preset found in {args.config}")
            sys.exit(1)
        self._preset = self._settings[self._preset_name]
        if args.date:
            self._date = args.date
        else:
            date = datetime.today() - timedelta(days=1)
            self._date = date.strftime("%Y-%m-%d")
        self._reporter = Reporter(self.log, self._api, self._api_helper)


    def _parse_block_settings(self, block, kind, state):
        """Parse a settings block. Every block may define a set of
        parameters, including a list of 'repos' (trees/branches). For
        every 'repos' item, this method will generate a query parameter
        set. All the query parameter sets will be based on the same base
        params.

        If the block doesn't define any repos, there'll be only one
        query parameter set created.

        If the block definition is empty, that is, if there aren't any
        specific query parameters, just return the base query parameter
        list.

        Returns a list of query parameter sets.

        """
        base_params = {
            'kind': kind,
            'state': state,
            'created__gt': self._date,
        }
        if not block:
            return [{**base_params}]

        query_params = []
        for item in block:
            item_base_params = base_params.copy()
            repos = []
            if 'repos' in item:
                for repo in item.pop('repos'):
                    new_repo = {}
                    for key, value in repo.items():
                        new_repo[f'data.kernel_revision.{key}'] = value
                    repos.append(new_repo)
            for key, value in item.items():
                item_base_params[key] = value
            if repos:
                for repo in repos:
                    query_params.append({**item_base_params, **repo})
            else:
                query_params.append(item_base_params)
        return query_params


    def _parse_settings(self):
        params = []
        for block_name, body in self._preset.items():
            if block_name == 'tests':
                params.extend(self._parse_block_settings(body, 'test', 'done'))
            elif block_name == 'kbuilds':
                params.extend(self._parse_block_settings(body, 'kbuild', 'done'))
            elif block_name == 'regressions':
                params.extend(self._parse_block_settings(body, 'regression', 'done'))
            else:
                # Other types of settings not implemented yet
                raise NotImplementedError("Settings type not implemented")
        return params


    def _run(self, ctx):
        #self._api.node.get(node_id='65bcd693c44aef50fd8aadba')
        params = self._parse_settings()
        for params_set in params:
            self.log.info(f"QUERY: {params_set}")
            nodes = self._api.node.find(params_set)
            self.log.info(f"Matches: {len(nodes)}")
            for node in nodes:
                node_obj = self._api_helper.get_node_obj(node, True)
                self.log.info(self._reporter.create_report(node_obj))
        return True


class cmd_run(Command):
    help = ("Checks for test results since a specific date "
            "and generates summary reports (single shot)")
    args = [
        {
            'name': '--config',
            'help': "Path to service-specific settings yaml file",
        },
    ]
    opt_args = [
        {
            'name': '--preset',
            'help': "Configuration preset to load ('default' if none)",
        },
        {
            'name': '--date',
            'help': ("Date from which to start collecting results "
                     "(YYYY-MM-DD). Default: one day before"),
        },
    ]

    def __call__(self, configs, args):
        return ResultsChecker(configs, args).run(args)


class cmd_loop(Command):
    help = ("Waits for test/regression results and generates summary "
            "reports (continuous mode)")
    args = cmd_run.args

    def __call__(self, configs, args):
        pass


if __name__ == '__main__':
    opts = parse_opts(SERVICE_NAME, globals())
    yaml_configs = opts.get_yaml_configs() or 'config/pipeline.yaml'
    configs = kernelci.config.load(yaml_configs)
    status = opts.command(configs, opts)
    sys.exit(0 if status is True else 1)
