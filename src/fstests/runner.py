#!/usr/bin/env python3
#
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Copyright (C) 2022 Collabora Limited
# Author: Alexandra Pereira <alexandra.pereira@collabora.com>

import os
import sys
import tempfile
import datetime
import traceback

import kernelci
import kernelci.config
import kernelci.db
import kernelci.lab
from kernelci.cli import Args, Command, parse_opts

TEMPLATES_PATHS = ['config/runtime',
                   '/etc/kernelci/runtime',
                   'src/fstests']

class FstestsRunner:
    def __init__(self, configs, args):
        api_token = os.getenv('API_TOKEN')
        self._db_config = configs['db_configs'][args.db_config]
        self._db = kernelci.db.get_db(self._db_config, api_token)
        self._device_configs = configs['device_types']
        self._gce = args.gce
        self._gce_project = args.gce_project
        self._gce_zone = args.gce_zone
        self._gs_bucket = args.gs_bucket
        self._kernel = args.kernel
        self._max_shards = args.max_shards
        self._njobs = args.j
        self._node_id = args.node_id
        self._plan = configs['test_plans']['fstests']
        self._skip_build = args.skip_build
        self._ssh_host = args.ssh_host
        self._ssh_key = args.ssh_key
        self._ssh_port = args.ssh_port
        self._ssh_user = args.ssh_user
        self._src_dir = args.src_dir
        self._output = args.output
        self._testcase = args.testcase
        self._testcfg = args.testcfg
        self._testgroup = args.testgroup
        self._xfstests_bld_path = args.xfstests_bld_path
        if not os.path.exists(self._output):
            os.makedirs(self._output)
        self._runtime = kernelci.lab.get_api(configs['labs']['shell'])

    def _create_node(self, tarball_node, plan_config):
        node = {
            'parent': tarball_node['_id'],
            'name': plan_config.name,
            'artifacts': tarball_node['artifacts'],
            'revision': tarball_node['revision'],
            'path': tarball_node['path'] + [plan_config.name],
        }
        return self._db.submit({'node': node}, True)[0]

    def _schedule_job(self, tarball_node, device_config, tmp):
        node = self._create_node(tarball_node, self._plan)
        revision = node['revision']
        try:
            params = {
                'db_config_yaml': self._db_config.to_yaml(),
                'gce': self._gce,
                'gce_project': self._gce_project,
                'gce_zone': self._gce_zone,
                'gs_bucket': self._gs_bucket,
                'kernel': self._kernel,
                'max_shards': self._max_shards,
                'name': self._plan.name,
                'njobs': self._njobs,
                'node_id': node['_id'],
                'revision': revision,
                'runtime': self._runtime.config.lab_type,
                'skip_build': self._skip_build,
                'ssh_host': self._ssh_host,
                'ssh_key': self._ssh_key,
                'ssh_port': self._ssh_port,
                'ssh_user': self._ssh_user,
                'src_dir': self._src_dir,
                'tarball_url': node['artifacts']['tarball'],
                'testcase': self._testcase,
                'testcfg': self._testcfg,
                'testgroup': self._testgroup,
                'output': tmp,
                'xfstests_bld_path' : self._xfstests_bld_path
            }
            params.update(self._plan.params)
            params.update(device_config.params)
            job = self._runtime.generate(params, device_config, self._plan,
                                         templates_paths=TEMPLATES_PATHS)
            output_file = self._runtime.save_file(job, tmp, params)
            job_result = self._runtime.submit(output_file)
        except Exception as e:
            # TBD: proper error handling
            traceback.print_exc()
        return job_result

    def _run_single_job(self, tarball_node, device):
        tstamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S-')
        try:
            tmp = tempfile.mkdtemp(prefix=tstamp, dir=self._output)
            job = self._schedule_job(tarball_node, device, tmp)
            print("Waiting...")
            job.wait()
            print("...done")
        except KeyboardInterrupt as e:
            print("Aborting.")
        except Exception as e:
            # TBD: proper error handling
            traceback.print_exc()
        finally:
            return True

    def _subscribe_and_run(self, filters):
        sub_id = self._db.subscribe_node_channel(filters=filters)
        print('Listening for checkouts')
        print('Press Ctrl-C to stop.')
        try:
            while True:
                tarball_node = self._db.receive_node(sub_id)
                print(f"Node tarball with id: {tarball_node['_id']}\
                        from revision: {tarball_node['revision']['commit'][:12]}")
                self._run_single_job(tarball_node, self._device_configs['shell'])
        except KeyboardInterrupt as e:
            print('Stopping.')
        except Exception as e:
            # TBD: proper error handling
            traceback.print_exc()
        finally:
            self._db.unsubscribe(sub_id)

    def _run_node_id(self):
        node = self._db.get_node(self._node_id)
        self._run_single_job(node, self._device_configs['shell'])

    def run(self):
        if self._node_id:
            self._run_node_id()
        else:
            self._subscribe_and_run({
                'name': 'checkout',
                'state': 'available',
            })
        # TBD: always?
        return True


class cmd_run(Command):
    help = 'KVM fstests runner'
    args = [
        Args.db_config, Args.output,
        {
            'name': '--xfstests-bld-path',
            'help': "xfstests build directory"
        },
    ]
    opt_args = [
        Args.j,
        Args.verbose,
        {
            'name': '--node-id',
            'help': "id of the checkout node rather than pub/sub",
        },
        {
            'name': '--src-dir',
            'help': "local directory containing the decompressed kernel code to use",
        },
        {
            'name': '--gce',
            'help': "run the tests in a GCE VM instance. If not defined, use KVM locally",
            'action': 'store_true',
        },
        {
            'name': '--kernel',
            'help': "path of the pre-built kernel image to use for the tests"
        },
        {
            'name': '--max-shards',
            'help': "maximum number of shards to use for GCE. If not defined it'll use the maximum available",
        },
        {
            'name': '--skip-build',
            'help': "don't configure or build the kernel.",
            'action': 'store_true',
        },
        {
            'name': '--ssh-host',
            'help': "Storage SSH host",
        },
        {
            'name': '--ssh-key',
            'help': "Path to the ssh key for uploading to storage",
        },
        {
            'name': '--ssh-port',
            'help': "Storage SSH port number",
            'type': int,
        },
        {
            'name': '--ssh-user',
            'help': "Storage SSH user name",
        },
        {
            'name': '--testcase',
            'help': "xfstests testcase to run. It can be a single config or a comma separated list"
        },
        {
            'name': '--testcfg',
            'help': "xfstests test configuration. It can be a single config or a comma separated list"
        },
        {
            'name': '--testgroup',
            'help': "xfstests test group to run"
        },
    ]

    def __call__(self, configs, args):
        return FstestsRunner(configs, args).run()


if __name__ == '__main__':
    opts = parse_opts('fstests_runner', globals())
    configs = kernelci.config.load('config/pipeline.yaml')
    status = opts.command(configs, opts)
    sys.exit(0 if status is True else 1)
