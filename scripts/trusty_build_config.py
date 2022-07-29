#!/usr/bin/env python3
#
# Copyright (C) 2018 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
# This test script to be used by the build server.
# It is supposed to be executed from trusty root directory
# and expects the following environment variables:
#
"""Parse trusty build and test configuration files."""

import argparse
import os
import re

script_dir = os.path.dirname(os.path.abspath(__file__))


class TrustyBuildConfigProject(object):
    """Stores build enabled status and test lists for a project

    Attributes:
        build: A boolean indicating if project should be built be default.
        tests: A list of commands to run to test this project.
        also_build: Set of project to also build if building this one.
    """

    def __init__(self):
        """Inits TrustyBuildConfigProject with an empty test list and no
           build."""
        self.build = False
        self.tests = []
        self.also_build = {}


class TrustyPortTestFlags(object):
    """Stores need flags for a test or provide flags for a test environment."""

    ALLOWED_FLAGS = {"android", "storage_boot", "storage_full", "smp4"}

    def __init__(self, **flags):
        self.flags = set()
        self.set(**flags)

    def set(self, **flags):
        """Set flags."""
        for name, arg in flags.items():
            if name in self.ALLOWED_FLAGS:
                if arg:
                    self.flags.add(name)
                else:
                    self.flags.discard(name)
            else:
                raise TypeError("Unexpected flag: " + name)

    def match_provide(self, provide):
        return self.flags.issubset(provide.flags)


class TrustyArchiveBuildFile(object):
    """Copy a file to archive directory after a build."""
    def __init__(self, src, dest, optional):
        self.src = src
        self.dest = dest
        self.optional = optional


class TrustyTest(object):
    """Stores a pair of a test name and a command to run"""
    def __init__(self, name, command, enabled):
        self.name = name
        self.command = command
        self.enabled = enabled


class TrustyHostTest(TrustyTest):
    """Stores a pair of a test name and a command to run on host."""

    pass


class TrustyPortTest(TrustyTest):
    """Stores a trusty port name for a test to run."""

    def __init__(self, port, enabled=True, timeout=None):
        super(TrustyPortTest, self).__init__(None, None, enabled)
        self.port = port
        self.need = TrustyPortTestFlags()
        self.timeout = timeout

    def needs(self, **need):
        self.need.set(**need)
        return self


class TrustyBuildConfig(object):
    """Trusty build and test configuration file parser."""

    def __init__(self, config_file=None, debug=False, android=None):
        """Inits TrustyBuildConfig.

        Args:
            config_file: Optional config file path. If omitted config file is
                found relative to script directory.
            debug: Optional boolean value. Set to True to enable debug messages.
        """
        self.debug = debug
        self.android = android
        self.projects = {}
        self.dist = []
        if config_file is None:
            config_file = os.path.join(script_dir, "build-config")
        self.read_config_file(config_file)

    def read_config_file(self, path, optional=False):
        """Main parser function called constructor or recursively by itself."""
        if optional and not os.path.exists(path):
            if self.debug:
                print("Skipping optional config file:", path)
            return

        if self.debug:
            print("Reading config file:", path)

        config_dir = os.path.dirname(path)

        def _flatten_list(inp, out):
            for obj in inp:
                if isinstance(obj, list):
                    _flatten_list(obj, out)
                else:
                    out.append(obj)

        def flatten_list(inp):
            out = []
            _flatten_list(inp, out)
            return out

        def include(path, optional=False):
            """Process include statement in config file."""
            if self.debug:
                print("include", path, "optional", optional)
            if path.startswith("."):
                path = os.path.join(config_dir, path)
            return self.read_config_file(path=path, optional=optional)

        def build(projects, enabled=True, dist=None):
            """Process build statement in config file."""
            for project_name in projects:
                if self.debug:
                    print("build", project_name, "enabled", enabled)
                project = self.get_project(project_name)
                project.build = bool(enabled)
            if dist:
                for item in dist:
                    assert isinstance(item, TrustyArchiveBuildFile), item
                    self.dist.append(item)

        def builddep(projects, needs):
            """Process build statement in config file."""
            for project_name in projects:
                project = self.get_project(project_name)
                for project_dep_name in needs:
                    project_dep = self.get_project(project_dep_name)
                    if self.debug:
                        print("build", project_name, "needs", project_dep_name)
                    project.also_build[project_dep_name] = project_dep

        def archive(src, dest=None, optional=False):
            return TrustyArchiveBuildFile(src, dest, optional)

        def testmap(projects, tests=()):
            """Process testmap statement in config file."""
            for project_name in projects:
                if self.debug:
                    print("testmap", project_name, "build", build)
                    for test in tests:
                        print(test)
                project = self.get_project(project_name)
                project.tests += flatten_list(tests)

        def hosttest(host_cmd, enabled=True):
            return TrustyHostTest("host-test:" + host_cmd,
                                  ["host_tests/" + host_cmd], enabled)

        def hosttests(tests):
            return [test for test in flatten_list(tests)
                    if isinstance(test, TrustyHostTest)]

        def porttest_match(test, provides):
            return (isinstance(test, TrustyPortTest)
                    and test.need.match_provide(provides))

        def porttests_filter(tests, provides):
            return [test for test in flatten_list(tests)
                    if porttest_match(test, provides)]

        def boottests(port_tests, provides=None):
            if provides is None:
                provides = TrustyPortTestFlags(storage_boot=True,
                                               smp4=True)
            trusty_tests = []
            for test in porttests_filter(port_tests, provides):
                if test.timeout:
                    timeout_args = ['--timeout', str(test.timeout)]
                else:
                    timeout_args = []

                trusty_tests += [TrustyTest("boot-test:" + test.port,
                                            ["run", "--headless", "--boot-test",
                                             test.port] + timeout_args,
                                            test.enabled)]
            return trusty_tests

        def androidtest(name, command, enabled=True, nameprefix="", runargs=(),
                        timeout=None):
            nameprefix = nameprefix + "android-test:"
            if timeout:
                timeout_args = ['--timeout', str(timeout)]
            else:
                timeout_args = []
            if self.android:
                android_args = ['--android', self.android]
            else:
                android_args = []
            runargs = list(runargs)
            return TrustyTest(nameprefix + name,
                              ["run", "--headless",
                               "--shell-command", command
                              ] + timeout_args + android_args + runargs,
                              enabled,
                             )

        def androidporttest(port, cmdargs, enabled, **kwargs):
            cmdargs = list(cmdargs)
            cmd = " ".join(
                [
                    "/vendor/bin/trusty-ut-ctrl",
                    port
                ] + cmdargs)
            return androidtest(port, cmd, enabled, **kwargs)

        def androidporttests(port_tests, provides=None, nameprefix="",
                             cmdargs=(), runargs=()):
            nameprefix = nameprefix + "android-port-test:"
            if provides is None:
                provides = TrustyPortTestFlags(android=True,
                                               storage_boot=True,
                                               storage_full=True,
                                               smp4=True)
            return [androidporttest(test.port, enabled=test.enabled,
                                    timeout=test.timeout,
                                    nameprefix=nameprefix, cmdargs=cmdargs,
                                    runargs=runargs)
                    for test in porttests_filter(port_tests, provides)]

        def needs(tests, *args, **kwargs):
            return [
                test.needs(*args, **kwargs)
                for test in flatten_list(tests)
            ]

        file_format = {
            "include": include,
            "build": build,
            "builddep": builddep,
            "archive": archive,
            "testmap": testmap,
            "hosttest": hosttest,
            "porttest": TrustyPortTest,
            "porttestflags": TrustyPortTestFlags,
            "hosttests": hosttests,
            "boottests": boottests,
            "androidtest": androidtest,
            "androidporttests": androidporttests,
            "needs": needs,
        }

        with open(path) as f:
            code = compile(f.read(), path, "eval")
            config = eval(code, file_format)  # pylint: disable=eval-used
            return flatten_list(config)

    def get_project(self, project):
        """Return TrustyBuildConfigProject entry for a project."""
        if project not in self.projects:
            self.projects[project] = TrustyBuildConfigProject()
        return self.projects[project]

    def get_projects(self, build=None, have_tests=None):
        """Return a list of projects.

        Args:
            build: If True only return projects that should be built. If False
                only return projects that should not be built. If None return
                both projects that should be built and not be built. (default
                None).
            have_tests: If True only return projects that have tests. If False
                only return projects that don't have tests. If None return
                projects regardless if they have tests. (default None).
        """

        def match(item):
            """filter function for get_projects."""
            project = self.projects[item]

            return ((build is None or build == project.build) and
                    (have_tests is None or
                     have_tests == bool(project.tests)))

        return filter(match, sorted(self.projects.keys()))


def list_projects(args):
    """Read config file and print a list of projects.

    See TrustyBuildConfig.get_projects for filtering options.

    Args:
        args: Program arguments.
    """
    config = TrustyBuildConfig(config_file=args.file, debug=args.debug)
    for project in sorted(config.get_projects(**dict(args.filter))):
        print(project)


def list_config(args):
    """Read config file and print all project and tests."""
    config = TrustyBuildConfig(config_file=args.file, debug=args.debug)
    print("Projects:")
    for project_name, project in sorted(config.projects.items()):
        print("  " + project_name + ":")
        print("    Build:", project.build)
        print("    Tests:")
        for test in project.tests:
            print("      " + test.name + ":")
            print("        " + str(test.command))

    for build in [True, False]:
        print()
        print("Build:" if build else "Don't build:")
        for tested in [True, False]:
            projects = config.get_projects(build=build, have_tests=tested)
            for project in sorted(projects):
                print("  " + project + ":")
                project_config = config.get_project(project)
                for test in project_config.tests:
                    print("    " + test.name)
            if projects and not tested:
                print("    No tests")


def any_test_name(regex, tests):
    """Checks the name of all tests in a list for a regex.

    This is intended only as part of the selftest facility, do not use it
    to decide how to consider actual tests.

    Args:
        tests: List of tests to check the names of
        regex: Regular expression to check them for (as a string)
    """

    return any([re.match(regex, test.name) is not None for test in tests])


def has_host(tests):
    """Checks for a host test in the provided tests by name.

    This is intended only as part of the selftest facility, do not use it
    to decide how to consider actual tests.

    Args:
        tests: List of tests to check for host tests
    """
    return any_test_name("host-test:", tests)


def has_unit(tests):
    """Checks for a unit test in the provided tests by name.

    This is intended only as part of the selftest facility, do not use it
    to decide how to consider actual tests.

    Args:
        tests: List of tests to check for unit tests
    """
    return any_test_name("boot-test:", tests)


def test_config(args):
    """Test config file parser.

    Uses a test config file where all projects have names that describe if they
    should be built and if they have tests.

    Args:
        args: Program arguments.
    """
    config_file = os.path.join(script_dir, "trusty_build_config_self_test_main")
    config = TrustyBuildConfig(config_file=config_file, debug=args.debug)

    projects_build = {}

    project_regex = re.compile(
        r"self_test\.build_(yes|no)\.tests_(none|host|unit|both)\..*")

    for build in [None, True, False]:
        projects_build[build] = {}
        for tested in [None, True, False]:
            projects = config.get_projects(build=build, have_tests=tested)
            projects_build[build][tested] = projects
            if args.debug:
                print("Build", build, "tested", tested, "count", len(projects))
            assert projects
            for project in projects:
                if args.debug:
                    print("-", project)
                m = project_regex.match(project)
                assert m
                if build is not None:
                    assert m.group(1) == ("yes" if build else "no")
                if tested is not None:
                    if tested:
                        assert (m.group(2) == "host" or
                                m.group(2) == "unit" or
                                m.group(2) == "both")
                    else:
                        assert m.group(2) == "none"

        assert(projects_build[build][None] ==
               sorted(projects_build[build][True] +
                      projects_build[build][False]))
    for tested in [None, True, False]:
        assert(projects_build[None][tested] ==
               sorted(projects_build[True][tested] +
                      projects_build[False][tested]))

    print("get_projects test passed")

    for project_name in config.get_projects():
        project = config.get_project(project_name)
        if args.debug:
            print(project_name, project)
        m = project_regex.match(project_name)
        assert m
        kind = m.group(2)
        if kind == "both":
            assert has_host(project.tests)
            assert has_unit(project.tests)
        elif kind == "unit":
            assert not has_host(project.tests)
            assert has_unit(project.tests)
        elif kind == "host":
            assert has_host(project.tests)
            assert not has_unit(project.tests)
        elif kind == "none":
            assert not has_host(project.tests)
            assert not has_unit(project.tests)
        else:
            assert False or "Unknown project kind"

        for i, test in enumerate(project.tests):
            host_m = re.match(r"host-test:self_test.*\.(\d+)",
                              test.name)
            unit_m = re.match(r"boot-test:self_test.*\.(\d+)",
                              test.name)
            if args.debug:
                print(project, i, test.name)
            m = host_m or unit_m
            assert m
            assert m.group(1) == str(i + 1)

    print("get_tests test passed")


def main():
    top = os.path.abspath(os.path.join(script_dir, "../../../../.."))
    os.chdir(top)

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--file")
    # work around for https://bugs.python.org/issue16308
    parser.set_defaults(func=lambda args: parser.print_help())
    subparsers = parser.add_subparsers()

    parser_projects = subparsers.add_parser("projects",
                                            help="list project names")

    group = parser_projects.add_mutually_exclusive_group()
    group.add_argument("--with-tests", action="append_const",
                       dest="filter", const=("have_tests", True),
                       help="list projects that have tests")
    group.add_argument("--without-tests", action="append_const",
                       dest="filter", const=("have_tests", False),
                       help="list projects that don't have tests")

    group = parser_projects.add_mutually_exclusive_group()
    group.add_argument("--all", action="append_const",
                       dest="filter", const=("build", None),
                       help="include disabled projects")
    group.add_argument("--disabled", action="append_const",
                       dest="filter", const=("build", False),
                       help="only list disabled projects")
    parser_projects.set_defaults(func=list_projects, filter=[("build", True)])

    parser_config = subparsers.add_parser("config", help="dump config")
    parser_config.set_defaults(func=list_config)

    parser_config = subparsers.add_parser("selftest", help="test config parser")
    parser_config.set_defaults(func=test_config)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
