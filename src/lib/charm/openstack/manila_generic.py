# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# The manila handlers class

# bare functions are provided to the reactive handlers to perform the functions
# needed on the class.
from __future__ import absolute_import

import re
import subprocess

import charmhelpers.contrib.openstack.utils as ch_utils
import charmhelpers.core.hookenv as hookenv
import charmhelpers.core.unitdata as unitdata
import charmhelpers.fetch

import charms_openstack.charm
import charms_openstack.adapters
import charms_openstack.ip as os_ip

# There are no additional packages to install.
PACKAGES = []
MANILA_DIR = '/etc/manila/'
MANILA_CONF = MANILA_DIR + "manila.conf"

# select the default release function and ssl feature
charms_openstack.charm.use_defaults('charm.default-select-release')

def strip_join(s, divider=" "):
    """Cleanup the string passed, split on whitespace and then rejoin it cleanly

    :param s: A sting to cleanup, remove non alpha chars and then represent the
        string.
    :param divider: The joining string to put the bits back together again.
    :returns: string
    """
    return divider.join(re.split(r'\s+', re.sub(r'([^\s\w-])+', '', (s or ""))))


###
# Compute some options to help with template rendering
@charms_openstack.adapters.config_property
def computed_use_password(config):
    """Return True if the generic driver should use a password rather than an
    ssh key.
    :returns: boolean
    """
    return (bool(config.driver_service_instance_password) &
            ((config.driver_auth_type or '').lower()
             in ('password', 'both')))


@charms_openstack.adapters.config_property
def computed_use_ssh(config):
    """Return True if the generic driver should use a password rather than an
    ssh key.
    :returns: boolean
    """
    return ((config.driver_auth_type or '').lower() in ('ssh', 'both'))


@charms_openstack.adapters.config_property
def computed_define_ssh(config):
    """Return True if the generic driver should define the SSH keys
    :returns: boolean
    """
    return (bool(config.driver_service_ssh_key) &
            bool(config.driver_service_ssh_key_public))


@charms_openstack.adapters.config_property
def computed_debug_level(config):
    """Return NONE, INFO, WARNING, DEBUG depending on the settings of
    options.debug and options.level
    :returns: string, NONE, WARNING, DEBUG
    """
    if not config.debug:
        return "NONE"
    if config.verbose:
        return "DEBUG"
    return "WARNING"


###
# Implementation of the Manila Charm classes

class ManilaGenericCharm(charms_openstack.charm.OpenStackCharm):
    """Generic backend driver configuration charm.  This configures a nominally
    named "generic" section along with nova, cinder and neutron sections to
    enable the generic NFS driver in the front end.
    """

    release = 'mitaka'
    name = 'manila-generic'
    packages = PACKAGES
    version_package = 'manila-api'  # need this for versioning the app
    api_ports = {}
    service_type = None

    default_service = None  # There is no service for this charm.
    services = []

    required_relations = []

    restart_map = {}

    # This is the command to sync the database
    sync_cmd = []

    def custom_assess_status_check(self):
        """Validate that the driver configuration is at least complete, and
        that it was valid when it used (either at configuration time or config
        changed time)

        :returns (status: string, message: string): the status, and message if
            there is a problem. Or (None, None) if there are no issues.
        """
        options = self.options
        if not options.driver_handles_share_servers:
            # Nothing to check if the driver doesn't handle share servers
            # directly.
            return None, None
        if not options.driver_service_image_name:
            return 'blocked', "Missing 'driver-service-image-name'"
        if not options.driver_service_instance_user:
            return 'blocked', "Missing 'driver-service-instance-user'"
        if not options.driver_service_instance_flavor_id:
            return ('blocked',
                    "Missing 'driver-service-instance-flavor-id")
        # Need at least one of the password or the keypair
        if (not bool(options.driver_service_instance_password) and
                not bool(options.driver_keypair_name)):
            return ('blocked',
                    "Need at least one of instance password or keypair name")
        return None, None

    def get_config_for_principal(self, auth_data):
        """Assuming that the configuration data is valid, return the
        configuration data for the principal charm.

        The format of the returned data is:
        {
            "complete": <boolean>,
            '<config file>': {
                '<section>: (
                    (key, value),
                    (key, value),
            )
        }

        If the configuration is not complete, or we don't have auth data from
        the principal charm, then we return:
        {
            "complete": false,
            "reason": <message>
        }

        :param auth_data: the raw dictionary received from the principal charm
        :returns: structure described above.
        """
        if not auth_data:
            return {"complete": False, "reason": "No authentication data"}
        state, message = self.custom_assess_status_check()
        if state:
            return {"complete": False, "reason": message}
        options = self.options  # tiny optimisation for less typing.
        # We have the auth data & the config is reasonably sensible.
        if options.share_backend_name is None:
            return {"complete": False,
                    "reason": "Problem: share-backend-name is not set"}
        # we use the same username/password/auth for each section as every
        # service user has then same permissions as admin.
        auth_section = (
            "# Only needed for the generic drivers as of Mitaka",
            ('username', auth_data['username']),
            ('password', auth_data['password']),
            ('project_domain_id', auth_data['project_domain_id']),
            ('project_name', auth_data['project_name']),
            ('user_domain_id', auth_data['user_domain_id']),
            ('auth_uri', auth_data['auth_uri']),
            ('auth_url', auth_data['auth_url']),
            ('auth_type', auth_data['auth_type']))

        # Expression is True if the generic driver should use a password rather
        # than an ssh key.
        if options.computed_use_password:
            service_instance_password = (
                "service_instance_password",
                options.driver_service_instance_password)
        else:
            service_instance_password = "# No generic password section"

        # Expression is True if the generic driver should use a password rather
        # than an ssh key.
        if options.computed_use_ssh:
            ssh_section = (
                ("path_to_private_key", "/etc/ssh/ssh_host_rsa_key"),
                ("path_to_public_key", "/etc/ssh/ssh_host_rsa_key.pub"),
                ("manila_service_keypair_name",
                 options.driver_keypair_name))
        else:
            ssh_section = "# No ssh section"

        # And finally configure the generic section
        generic_section = (
            "# Set usage of Generic driver which uses cinder as backend.",
            "share_driver = manila.share.drivers.generic.GenericShareDriver",
            "",
            "# Generic driver supports both driver modes - "
            "with and without handling",
            "# of share servers. So, we need to define explicitly which one "
            "we are",
            "# enabling using this driver.",
            ("driver_handles_share_servers",
             options.driver_handles_share_servers),
            "",
            "# The flavor that Manila will use to launch the instance.",
            ("service_instance_flavor_id",
             options.driver_service_instance_flavor_id),
            "",
            "# Generic driver uses a glance image for building service VMs "
            "in nova.",
            "# The following options specify the image to use.",
            "# We use the latest build of [1].",
            "# [1] https://github.com/openstack/manila-image-elements",
            ("service_instance_user",
             options.driver_service_instance_user),
            ("service_image_name", options.driver_service_image_name),
            ("connect_share_server_to_tenant_network",
             options.driver_connect_share_server_to_tenant_network),
            "",
            "# These will be used for keypair creation and inserted into",
            "# service VMs.",
            "# TODO: this presents a problem with HA and failover - as the"
            "keys",
            "# will no longer be the same -- need to be able to set these via",
            "# a config option.",
            service_instance_password,
            ssh_section,
            "",
            "# Custom name for share backend.",
            ("share_backend_name", options.share_backend_name))

        return {
            "complete": True,
            MANILA_CONF: {
                "[nova]": auth_section,
                "[neutron]": auth_section,
                "[cinder]": auth_section,
                "[{}]".format(options.share_backend_name): generic_section,
            },
        }
