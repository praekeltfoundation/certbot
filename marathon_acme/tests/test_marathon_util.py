import pytest

from testtools import ExpectedException
from testtools.assertions import assert_that
from testtools.matchers import Equals

from marathon_acme.marathon_util import get_number_of_app_ports

TEST_APP = {
    'id': '/foovu1',
    'cmd': 'python -m http.server 8080',
    'args': None,
    'user': None,
    'env': {},
    'instances': 1,
    'cpus': 0.1,
    'mem': 32,
    'disk': 0,
    'gpus': 0,
    'executor': '',
    'constraints': [],
    'uris': [],
    'fetch': [],
    'storeUrls': [],
    'backoffSeconds': 1,
    'backoffFactor': 1.15,
    'maxLaunchDelaySeconds': 3600,
    'container': None,
    'healthChecks': [],
    'readinessChecks': [],
    'dependencies': [],
    'upgradeStrategy': {
        'minimumHealthCapacity': 1,
        'maximumOverCapacity': 1,
    },
    'labels': {},
    'ipAddress': None,
    'version': '2017-05-22T08:53:15.476Z',
    'residency': None,
    'secrets': {},
    'taskKillGracePeriodSeconds': None,
    'unreachableStrategy': {
        'inactiveAfterSeconds': 300,
        'expungeAfterSeconds': 600,
    },
    'killSelection': 'YOUNGEST_FIRST',
    'versionInfo': {
        'lastScalingAt': '2017-05-22T08:53:15.476Z',
        'lastConfigChangeAt': '2017-05-22T08:53:15.476Z',
    },
    'tasksStaged': 0,
    'tasksRunning': 1,
    'tasksHealthy': 0,
    'tasksUnhealthy': 0,
    'deployments': [],
}

CONTAINER_HOST_NETWORKING = {
    'type': 'DOCKER',
    'volumes': [],
    'docker': {
        'image': 'praekeltfoundation/marathon-lb:1.6.0',
        'network': 'HOST',
        'portMappings': [],
        'privileged': True,
        'parameters': [],
        'forcePullImage': False
    }
}

CONTAINER_USER_NETWORKING = {
    'type': 'DOCKER',
    'volumes': [],
    'docker': {
        'image': 'python:3-alpine',
        'network': 'USER',
        'portMappings': [
            {
                'containerPort': 8080,
                'servicePort': 10004,
                'protocol': 'tcp',
                'name': 'foovu1http',
                'labels': {
                    'VIP_0': '/foovu1:8080',
                },
            },
        ],
        'privileged': False,
        'parameters': [],
        'forcePullImage': False,
    },
}

CONTAINER_BRIDGE_NETWORKING = {
    'type': 'DOCKER',
    'volumes': [],
    'docker': {
        'image': 'index.docker.io/jerithorg/testapp:0.0.12',
        'network': 'BRIDGE',
        'portMappings': [
            {
                'containerPort': 5858,
                'hostPort': 0,
                'servicePort': 10008,
                'protocol': 'tcp',
                'labels': {},
            },
        ],
        'privileged': False,
        'parameters': [],
        'forcePullImage': True,
    },
}

# We've never run a container with the Mesos containerizer before. This is from
# https://mesosphere.github.io/marathon/docs/external-volumes.html
CONTAINER_MESOS = {
    'type': 'MESOS',
    'volumes': [
        {
            'containerPath': 'test-rexray-volume',
            'external': {
                'size': 100,
                'name': 'my-test-vol',
                'provider': 'dvdi',
                'options': {'dvdi/driver': 'rexray'},
            },
            'mode': 'RW',
        },
    ],
}

# https://github.com/mesosphere/marathon/blob/v1.5.1/docs/docs/networking.md#host-mode
NETWORKS_CONTAINER_HOST_MARATHON15 = [{'mode': 'host'}]
CONTAINER_MESOS_HOST_NETWORKING_MARATHON15 = {
    'type': 'MESOS',
    'docker': {
        'image': 'my-image:1.0'
    },
}

# https://github.com/mesosphere/marathon/blob/v1.5.1/docs/docs/networking.md#specifying-ports-1
NETWORKS_CONTAINER_BRIDGE_MARATHON15 = [{'mode': 'container/bridge'}]
CONTAINER_BRIDGE_NETWORKING_MARATHON15 = {
    'type': 'DOCKER',
    'docker': {
      'forcePullImage': True,
      'image': 'praekeltfoundation/mc2:release-3.11.2',
      'parameters': [
        {
          'key': 'add-host',
          'value': 'servicehost:172.17.0.1'
        }
      ],
      'privileged': False
    },
    'volumes': [],
    'portMappings': [
      {
        'containerPort': 80,
        'hostPort': 0,
        'labels': {},
        'protocol': 'tcp',
        'servicePort': 10005
      }
    ]
}
CONTAINER_MESOS_BRIDGE_NETWORKING_MARATHON15 = {
    'type': 'MESOS',
    'docker': {
        'image': 'my-image:1.0'
    },
    'portMappings': [
        {'containerPort': 80, 'hostPort': 0, 'name': 'http'},
        {'containerPort': 443, 'hostPort': 0, 'name': 'https'},
        {'containerPort': 4000, 'hostPort': 0, 'name': 'mon'}
    ]
}

# https://github.com/mesosphere/marathon/blob/v1.5.1/docs/docs/networking.md#enabling-container-mode
NETWORKS_CONTAINER_USER_MARATHON15 = [{'mode': 'container', 'name': 'dcos'}]
CONTAINER_USER_NETWORKING_MARATHON15 = {
    'type': 'DOCKER',
    'docker': {
      'forcePullImage': False,
      'image': 'python:3-alpine',
      'parameters': [],
      'privileged': False
    },
    'volumes': [],
    'portMappings': [
      {
        'containerPort': 8080,
        'labels': {
          'VIP_0': '/foovu1:8080'
        },
        'name': 'foovu1http',
        'protocol': 'tcp',
        'servicePort': 10004
      }
    ],
}

IP_ADDRESS_NO_PORTS = {
    'groups': [],
    'labels': {},
    'discovery': {
        'ports': [],
    },
    'networkName': 'dcos',
}

IP_ADDRESS_TWO_PORTS = {
    'groups': [],
    'labels': {},
    'discovery': {
        'ports': [
            {'number': 80, 'name': 'http', 'protocol': 'tcp'},
            {'number': 443, 'name': 'http', 'protocol': 'tcp'},
        ],
    },
}

PORT_DEFINITIONS_ONE_PORT = [
    {
        'port': 10008,
        'protocol': 'tcp',
        'name': 'default',
        'labels': {},
    },
]


@pytest.fixture
def test_app():
    return TEST_APP.copy()


class TestGetNumberOfAppPortsFunc(object):
    def test_host_networking(self, test_app):
        """
        When the app uses Docker containers with HOST networking, the ports
        should be counted from the 'portDefinitions' field.
        """
        test_app['container'] = CONTAINER_HOST_NETWORKING
        test_app['portDefinitions'] = PORT_DEFINITIONS_ONE_PORT

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(1))

    def test_user_networking(self, test_app):
        """
        When the app uses a Docker container with USER networking, it will have
        its 'ipAddress' field set. The ports should be counted using the
        'portMappings' field in the container definition.
        """
        test_app['container'] = CONTAINER_USER_NETWORKING
        test_app['ipAddress'] = IP_ADDRESS_NO_PORTS

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(1))

    def test_ip_per_task_no_container(self, test_app):
        """
        When the app uses ip-per-task networking, but is not running in a
        container, then the ports should be counted from the 'ipAddress'
        field.
        """
        test_app['ipAddress'] = IP_ADDRESS_TWO_PORTS

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(2))

    def test_ip_per_task_mesos_containerizer(self, test_app):
        """
        When the app uses ip-per-task networking, with the Mesos containerizer,
        the ports should be counted from the 'ipAddress' field.
        """
        test_app['container'] = CONTAINER_MESOS
        test_app['ipAddress'] = IP_ADDRESS_TWO_PORTS

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(2))

    def test_bridge_networking(self, test_app):
        """
        When the app uses Docker containers with BRIDGE networking, the ports
        should be counted from the 'portDefinitions' field.
        """
        test_app['container'] = CONTAINER_BRIDGE_NETWORKING
        test_app['portDefinitions'] = PORT_DEFINITIONS_ONE_PORT

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(1))

    def test_bridge_networking_no_port_definitions(self, test_app):
        """
        When the app uses Docker containers with BRIDGE networking, but the
        'portDefinitions' field is not defined, the ports should be counted
        from the 'ports' field.
        """
        test_app['container'] = CONTAINER_BRIDGE_NETWORKING
        test_app['ports'] = [10008, 10009]

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(2))

    def test_host_networking_mesos_marathon15(self, test_app):
        """
        For Marathon 1.5+, when the app uses Mesos containers with host
        networking, the ports should be counted from the 'portDefinitions'
        field.
        """
        test_app['container'] = CONTAINER_MESOS_HOST_NETWORKING_MARATHON15
        test_app['networks'] = NETWORKS_CONTAINER_HOST_MARATHON15
        test_app['portDefinitions'] = PORT_DEFINITIONS_ONE_PORT

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(1))

    def test_bridge_networking_marathon15(self, test_app):
        """
        For Marathon 1.5+, when the app uses Docker containers with
        'container/bridge' networking, the ports should be counted from the
        ``container.portMappings`` field.
        """
        test_app['container'] = CONTAINER_BRIDGE_NETWORKING_MARATHON15
        test_app['networks'] = NETWORKS_CONTAINER_BRIDGE_MARATHON15

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(1))

    def test_bridge_networking_mesos_marathon15(self, test_app):
        """
        For Marathon 1.5+, when the app uses Mesos containers with
        'container/bridge' networking, the ports should be counted from the
        ``container.portMappings`` field.
        """
        test_app['container'] = CONTAINER_MESOS_BRIDGE_NETWORKING_MARATHON15
        test_app['networks'] = NETWORKS_CONTAINER_BRIDGE_MARATHON15

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(3))

    def test_user_networking_marathon15(self, test_app):
        """
        For Marathon 1.5+, when the app uses Docker containers with 'container'
        networking, the ports should be counted from the
        ``container.portMappings`` field.
        """
        test_app['container'] = CONTAINER_USER_NETWORKING_MARATHON15
        test_app['networks'] = NETWORKS_CONTAINER_USER_MARATHON15

        num_ports = get_number_of_app_ports(test_app)
        assert_that(num_ports, Equals(1))

    def test_unknown_networking_mode(self, test_app):
        """
        When an app is defined with an unknown networking mode, an error is
        raised.
        """
        test_app['networks'] = [{'mode': 'container/iptables'}]

        with ExpectedException(
            RuntimeError,
                r"Unknown Marathon networking mode 'container/iptables'"):
            get_number_of_app_ports(test_app)
