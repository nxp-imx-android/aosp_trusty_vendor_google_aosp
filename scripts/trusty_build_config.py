#!/usr/bin/env python2.7
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


class TrustyBuildConfigProject(object):
    """Stores build enabled status and test lists for a project

    Attributes:
        build: A boolean indicating if project should be built be default.
        host_tests: List of host_tests to run for this project.
        unit_tests: List of unit_tests to run for this project.
    """

    def __init__(self):
        """Inits TrustyBuildConfigProject with empty test lists and no build."""
        self.build = False
        self.host_tests = []
        self.unit_tests = []


class TrustyBuildConfig(object):
    """Trusty build and test configuration file parser."""

    def __init__(self, config_file=None, debug=False):
        """Inits TrustyBuildConfig.

        Args:
            config_file: Optional config file path. If omitted config file is
                found relative to script directory.
            debug: Optional boolean value. Set to True to enable debug messages.
        """
        self.debug = debug
        self.projects = {}
        if config_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(script_dir, "build-config")
        self.read_config_file(config_file)

    def read_config_file(self, path, optional=False):
        """Main parser function called constructor or recursively by itself."""
        if optional and not os.path.exists(path):
            if self.debug:
                print "Skipping optional config file:", path
            return

        if self.debug:
            print "Reading config file:", path

        config_dir = os.path.dirname(path)

        def include(path, optional=False):
            """Process include statement in config file."""
            if self.debug:
                print "include", path, "optional", optional
            self.read_config_file(path=os.path.join(config_dir, path),
                                  optional=optional)

        def build(projects, enabled=True):
            """Process build statement in config file."""
            for project_name in projects:
                if self.debug:
                    print "build", project_name, "enabled", enabled
                project = self.get_project(project_name)
                project.build = bool(enabled)

        def testmap(projects, host_tests=(), unit_tests=()):
            """Process testmap statement in config file."""
            for project_name in projects:
                if self.debug:
                    print "testmap", project_name, "build", build
                    for host_test in host_tests:
                        print "  host_test", host_test
                    for unit_test in unit_tests:
                        print "  unit_test", unit_test
                project = self.get_project(project_name)
                project.host_tests += host_tests
                project.unit_tests += unit_tests

        file_format = {
            "include": include,
            "build": build,
            "testmap": testmap,
        }

        with open(path) as f:
            eval(f.read(), file_format)

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
                     have_tests == bool(project.host_tests or
                                        project.unit_tests)))

        return filter(match, sorted(self.projects.keys()))


def list_projects(args):
    """Read config file and print a list of projects.

    See TrustyBuildConfig.get_projects for filtering options.

    Args:
        args: Program arguments.
    """
    config = TrustyBuildConfig(config_file=args.file, debug=args.debug)
    for project in sorted(config.get_projects(**dict(args.filter))):
        print project


def list_config(args):
    """Read config file and print all project and tests."""
    config = TrustyBuildConfig(config_file=args.file, debug=args.debug)
    print "Projects:"
    for project_name, project in sorted(config.projects.items()):
        print "  " + project_name + ":"
        print "    Build:", project.build
        print "    Host tests:"
        for host_test in project.host_tests:
            print "      " + host_test
        print "    Unit tests:"
        for unit_test in project.unit_tests:
            print "      " + unit_test

    for build in [True, False]:
        print
        print "Build:" if build else "Don't build:"
        for tested in [True, False]:
            projects = config.get_projects(build=build, have_tests=tested)
            for project in sorted(projects):
                print "  " + project + ":"
                tests = config.get_project(project)
                for test_type, test_list in [("Host-tests", tests.host_tests),
                                             ("Unit-tests", tests.unit_tests)]:
                    if test_list:
                        print "    " + test_type + ":"
                        for test in test_list:
                            print "      " + test
            if projects and not tested:
                print "    No tests"


def test_config(args):
    """Test config file parser.

    Uses a dummy config file where all projects have names that describe if they
    should be built and if they have tests.

    Args:
        args: Program arguments.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
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
                print "Build", build, "tested", tested, "count", len(projects)
            assert projects
            for project in projects:
                if args.debug:
                    print "-", project
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

    print "get_projects test passed"

    for project in config.get_projects():
        tests = config.get_project(project)
        if args.debug:
            print project, tests
        m = project_regex.match(project)
        assert m
        if tests.host_tests:
            if tests.unit_tests:
                assert m.group(2) == "both"
            else:
                assert m.group(2) == "host"
        else:
            if tests.unit_tests:
                assert m.group(2) == "unit"
            else:
                assert m.group(2) == "none"

        for i, host_test in enumerate(tests.host_tests):
            m = re.match(r"self_test\.host_test.*\.(\d+)", host_test)
            if args.debug:
                print project, "host_test", i, host_test
            assert m
            assert m.group(1) == str(i + 1)

        for i, unit_test in enumerate(tests.unit_tests):
            m = re.match(r"self_test\.unit_test.*\.(\d+)", unit_test)
            if args.debug:
                print project, "unit_test", i, unit_test
            assert m
            assert m.group(1) == str(i + 1)

    print "get_tests test passed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--file")
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
