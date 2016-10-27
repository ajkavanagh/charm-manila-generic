# Overview

This charm provides the configuration to configure the generic backend in the
related manila charm in an OpenStack cloud.

# Usage

The charm relies on the prinical manila charm, and is a subordinate to it.  It
provides configuration data to the manila-share service (which is provided by
the manila charm with a role that includes 'share'.

If multiple, _different_, generic backend configurations are required then the
`share-backend-name` config option should be used to differentiate between the
configuration sections.

_Note_: this subordinate charm requests that manila configure the nova, neutron
and cinder sections that the generic driver needs to launch NFS share instances
that provide NFS/CIFS services within their tenant networks.

# Bugs

Please report bugs on [Launchpad](https://bugs.launchpad.net/charm-manila-generic/+filebug).

For general questions please refer to the OpenStack [Charm Guide](https://github.com/openstack/charm-guide).
