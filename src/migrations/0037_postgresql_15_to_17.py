#!/usr/bin/env python3
#
# Copyright (c) 2024 YunoHost Contributors
#
# This file is part of YunoHost (see https://yunohost.org)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import os
import subprocess
import time
from logging import getLogger

from moulinette import m18n

from ..tools import Migration
from ..utils.error import YunohostError, YunohostValidationError
from ..utils.system import free_space_in_directory, space_used_by_directory

logger = getLogger("yunohost.migration")

PREVIOUS_VERSION = "15"
TARGET_VERSION = "17"
LINUX_DISTRO_CODENAME = "trixie"
MIGRATION_NUMBER = 37

class MyMigration(Migration):
    f"Migrate DBs from Postgresql {PREVIOUS_VERSION} to {TARGET_VERSION} after migrating to {LINUX_DISTRO_CODENAME.capitalize()}"

    dependencies = [f"migrate_to_{LINUX_DISTRO_CODENAME}"]

    def run(self):
        if (
            os.system(
                'grep -A10 "ynh-deps" /var/lib/dpkg/status | grep -E "Package:|Depends:" | grep -B1 postgresql'
            )
            != 0
        ):
            logger.info("No YunoHost app seem to require postgresql... Skipping!")
            return

        if not self.package_is_installed(f"postgresql-{PREVIOUS_VERSION}"):
            logger.warning(m18n.n(f"migration_{MIGRATION_NUMBER:04d}_postgresql_{PREVIOUS_VERSION}_not_installed"))
            return

        if not self.package_is_installed(f"postgresql-{TARGET_VERSION}"):
            raise YunohostValidationError(f"migration_{MIGRATION_NUMBER:04d}_postgresql_{TARGET_VERSION}_not_installed")

        # Make sure there's a 15 cluster
        try:
            self.runcmd(f"pg_lsclusters | grep -q '^{PREVIOUS_VERSION} '")
        except Exception:
            logger.warning(
                f"It looks like there's not active {PREVIOUS_VERSION} cluster, so probably don't need to run this migration"
            )
            return

        if not space_used_by_directory(
            f"/var/lib/postgresql/{PREVIOUS_VERSION}"
        ) > free_space_in_directory("/var/lib/postgresql"):
            raise YunohostValidationError(
                f"migration_{MIGRATION_NUMBER:04d}_not_enough_space", path="/var/lib/postgresql/"
            )

        self.runcmd("systemctl stop postgresql")
        time.sleep(3)
        self.runcmd(
            f"LC_ALL=C pg_dropcluster --stop {TARGET_VERSION} main || true"
        )  # We do not trigger an exception if the command fails because that probably means cluster TARGET_VERSION doesn't exists, which is fine because it's created during the pg_upgradecluster)
        time.sleep(3)
        self.runcmd(f"LC_ALL=C pg_upgradecluster -m upgrade {PREVIOUS_VERSION} main -v {TARGET_VERSION}")
        self.runcmd(f"LC_ALL=C pg_dropcluster --stop {PREVIOUS_VERSION} main")
        self.runcmd("systemctl start postgresql")

    def package_is_installed(self, package_name):
        (returncode, out, err) = self.runcmd(
            "dpkg --list | grep '^ii ' | grep -q -w {}".format(package_name),
            raise_on_errors=False,
        )
        return returncode == 0

    def runcmd(self, cmd, raise_on_errors=True):
        logger.debug("Running command: " + cmd)

        p = subprocess.Popen(
            cmd,
            shell=True,
            executable="/bin/bash",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        out, err = p.communicate()
        returncode = p.returncode
        if raise_on_errors and returncode != 0:
            raise YunohostError(
                "Failed to run command '{}'.\nreturncode: {}\nstdout:\n{}\nstderr:\n{}\n".format(
                    cmd, returncode, out, err
                )
            )

        out = out.strip().split(b"\n")
        return (returncode, out, err)
