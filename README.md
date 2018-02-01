# marathon-acme

[![PyPI](https://img.shields.io/pypi/v/marathon-acme.svg)](https://pypi.python.org/pypi/marathon-acme)
[![Build Status](https://travis-ci.org/praekeltfoundation/marathon-acme.svg?branch=develop)](https://travis-ci.org/praekeltfoundation/marathon-acme)
[![codecov](https://codecov.io/gh/praekeltfoundation/marathon-acme/branch/develop/graph/badge.svg)](https://codecov.io/gh/praekeltfoundation/marathon-acme)

Automate [ACME](https://en.wikipedia.org/wiki/Automated_Certificate_Management_Environment) certificates for [Marathon](https://mesosphere.github.io/marathon/) apps served by [`marathon-lb`](https://github.com/mesosphere/marathon-lb)

## How it works
There is one big requirement for deploying `marathon-acme`: there must be shared persistent storage between `marathon-acme` and all `marathon-lb` instances. This will be used to store the certificates.

 1. `marathon-acme` watches Marathon for changes to app definitions.
 2. It collects the values of all `MARATHON_ACME_{n}_DOMAIN` labels on apps. This will form the set of domains to fetch certificates for.
 3. It generates, verifies and stores certificates for any new domains using the configured ACME certificate authority.
 4. It tells `marathon-lb` to reload using the `marathon-lb` HTTP API.
 5. It issues new certificates for soon-to-expire certificates once a day.

`marathon-acme` is written in Python using [Twisted](https://twistedmatrix.com/trac/). The certificate issuing functionality is possible thanks to the [`txacme`](https://github.com/mithrandi/txacme) library.

The ACME provider that most people are likely to use is [Let's Encrypt](https://letsencrypt.org/). Before using `marathon-acme` with Let's Encrypt, make sure you are aware of their [rate limits](https://letsencrypt.org/docs/rate-limits/).

## Usage
`marathon-acme` is available as a pip-installable Python package on [PyPI](https://pypi.python.org/pypi/marathon-acme). However, most users will probably want to use the Docker image available from [Docker Hub](https://hub.docker.com/r/praekeltfoundation/marathon-acme/).

```
> $ docker run --rm praekeltfoundation/marathon-acme --help
usage: marathon-acme [-h] [-a ACME] [-e EMAIL] [-m MARATHON[,MARATHON,...]]
                     [-l LB[,LB,...]] [-g GROUP] [--allow-multiple-certs]
                     [--listen LISTEN] [--sse-timeout SSE_TIMEOUT]
                     [--log-level {debug,info,warn,error,critical}]
                     storage-dir

Automatically manage ACME certificates for Marathon apps

positional arguments:
  storage-dir           Path to directory for storing certificates

optional arguments:
  -h, --help            show this help message and exit
  -a ACME, --acme ACME  The address for the ACME Directory Resource (default:
                        https://acme-v01.api.letsencrypt.org/directory)
  -e EMAIL, --email EMAIL
                        An email address to register with the ACME service
                        (optional)
  -m MARATHON[,MARATHON,...], --marathon MARATHON[,MARATHON,...]
                        The addresses for the Marathon HTTP API (default:
                        http://marathon.mesos:8080)
  -l LB[,LB,...], --lb LB[,LB,...]
                        The addresses for the marathon-lb HTTP API (default:
                        http://marathon-lb.marathon.mesos:9090)
  -g GROUP, --group GROUP
                        The marathon-lb group to issue certificates for
                        (default: external)
  --allow-multiple-certs
                        Allow multiple certificates for a single app port.
                        This allows multiple domains for an app, but is not
                        recommended.
  --listen LISTEN       The address for the port to listen on (default: :8000)
  --sse-timeout SSE_TIMEOUT
                        Amount of time in seconds to wait for some event data
                        to be received from Marathon. Set to 0 to disable.
                        (default: 60)
  --log-level {debug,info,warn,error,critical}
                        The minimum severity level to log messages at
                        (default: info)
  --version             show program's version number and exit
```

### `marathon-acme` app definition
`marathon-acme` should be deployed as a Marathon app.

```json
{
  "id": "/marathon-acme",
  "cpus": 0.01,
  "mem": 128.0,
  "args": [
    "--email", "letsencrypt@example.com",
    "--marathon", "http://marathon1:8080,http://marathon2:8080,http://marathon3:8080",
    "--lb", "http://lb1:9090,http://lb2:9090",
    "/var/lib/marathon-acme"
  ],
  "labels": {
    "HAPROXY_GROUP": "external",
    "HAPROXY_0_VHOST": "marathon-acme.example.com",
    "HAPROXY_0_BACKEND_WEIGHT": "1",
    "HAPROXY_0_PATH": "/.well-known/acme-challenge/",
    "HAPROXY_0_HTTP_FRONTEND_ACL_WITH_PATH": "  acl host_{cleanedUpHostname} hdr(host) -i {hostname}\n  acl path_{backend} path_beg {path}\n  redirect prefix http://{hostname} code 302 if !host_{cleanedUpHostname} path_{backend}\n  use_backend {backend} if host_{cleanedUpHostname} path_{backend}\n"
  },
  "container": {
    "type": "DOCKER",
    "docker": {
      "image": "praekeltfoundation/marathon-acme",
      "network": "BRIDGE",
      "portMappings": [
        { "containerPort": 8000, "hostPort": 0 }
      ],
      "parameters": [
        {
          "value": "my-volume-driver",
          "key": "volume-driver"
        },
        {
          "value": "marathon-acme-certs:/var/lib/marathon-acme",
          "key": "volume"
        }
      ],
    }
  }
}
```
The above should mostly be standard across different deployments. The volume parameters will depend on your particular networked storage solution.

#### `HAPROXY` labels
```json
"labels": {
  "HAPROXY_GROUP": "external",
  "HAPROXY_0_VHOST": "marathon-acme.example.com",
  "HAPROXY_0_BACKEND_WEIGHT": "1",
  "HAPROXY_0_PATH": "/.well-known/acme-challenge/",
  "HAPROXY_0_HTTP_FRONTEND_ACL_WITH_PATH": "  acl host_{cleanedUpHostname} hdr(host) -i {hostname}\n  acl path_{backend} path_beg {path}\n  redirect prefix http://{hostname} code 302 if !host_{cleanedUpHostname} path_{backend}\n  use_backend {backend} if host_{cleanedUpHostname} path_{backend}\n"
}
```
Several special `marathon-lb` labels are needed in order to forward all HTTP requests whose path begins with `/.well-known/acme-challenge/` to `marathon-acme`, in order to serve ACME [HTTP challenge](https://ietf-wg-acme.github.io/acme/#rfc.section.7.2) responses.

##### `HAPROXY_GROUP`
```
external
```
`marathon-lb` instances are assigned a group. Only Marathon apps with a `HAPROXY_GROUP` label that matches their group are routed with that instance. "external" is the common name for publicly-facing load balancers.

##### `HAPROXY_0_VHOST`
```
marathon-acme.example.com
```
`marathon-acme` needs its own domain to respond to ACME challenge requests on. This domain must resolve to your `marathon-lb` instance(s).

##### `HAPROXY_0_BACKEND_WEIGHT`
```
1
```
We want this rule in HAProxy's config file to come before any others so that requests are routed to `marathon-acme` before we do the (usually) domain-based routing for the other Marathon apps. The default weight is `0`, so we set to `1` so that the rule comes first.

##### `HAPROXY_0_PATH`
```
/.well-known/acme-challenge/
```
This is the beginning of the HTTP path to ACME validation challenges.

##### `HAPROXY_0_HTTP_FRONTEND_ACL_WITH_PATH`
```
  acl host_{cleanedUpHostname} hdr(host) -i {hostname}
  acl path_{backend} path_beg {path}
  redirect prefix http://{hostname} code 302 if !host_{cleanedUpHostname} path_{backend}
  use_backend {backend} if host_{cleanedUpHostname} path_{backend}
```
This is where it gets complicated... It’s possible to edit the templates used for generating the HAProxy on a per-app basis using labels. This is necessary because by default `marathon-lb` will route based on domain first, but we don’t want to do that. You can see the standard template [here](https://github.com/mesosphere/marathon-lb/blob/master/Longhelp.md#haproxy_http_frontend_acl_with_path).

Here, we add an extra `redirect` rule. This redirects all requests matching the ACME challenge path to `marathon-acme`, except those requests already headed for `marathon-acme`. The Let's Encrypt server will follow redirects.

#### `HAPROXY` HTTPS labels
It is possible to have `marathon-acme` serve ACME challenge requests over HTTPS, although this is usually not necessary. In this case, a certificate needs to be issued for `marathon-acme` and the HTTP redirect label needs to be modified:
```json
"labels": {
  ...,
  "MARATHON_ACME_0_DOMAIN": "marathon-acme.example.com",
  "HAPROXY_0_HTTP_FRONTEND_ACL_WITH_PATH": "  acl host_{cleanedUpHostname} hdr(host) -i {hostname}\n  acl path_{backend} path_beg {path}\n  redirect prefix https://{hostname} code 302 if path_{backend}\n"
}
```
Note that using the `HAPROXY_0_REDIRECT_TO_HTTPS` label for `marathon-acme` will break things. This label is difficult for us to use because of the way `marathon-lb`'s templating works.

##### `MARATHON_ACME_0_DOMAIN`
```
marathon-acme.example.com
```
Here we set up `marathon-acme` to fetch a certificate for itself.

##### `HAPROXY_0_HTTP_FRONTEND_ACL_WITH_PATH`
```
  acl host_{cleanedUpHostname} hdr(host) -i {hostname}
  acl path_{backend} path_beg {path}
  redirect prefix https://{hostname} code 302 if path_{backend}
```
We redirect to the HTTPS address (`https://{hostname}`) for all domains (including `marathon-acme`'s) for requests to the ACME challenge path. The `use_backend` directive can now be removed since the backend is never used over HTTP as all requests are redirected.

**Note that this label can only be set after `marathon-acme` has fetched the first certificate for its own domain.** In other words, set the `MARATHON_ACME_0_DOMAIN` _first_ and make sure it has taken effect before setting this one.

#### Docker images
Docker images are available from [Docker Hub](https://hub.docker.com/r/praekeltfoundation/marathon-acme/). There are two different streams of Docker images available:
* `:latest`/`:<version>`: Tracks the latest released version of `marathon-acme` on [PyPI](https://pypi.python.org/pypi/marathon-acme). The Dockerfile for these is in the [`praekeltfoundation/docker-marathon-acme`](https://github.com/praekeltfoundation/docker-marathon-acme) repo.
* `:develop`: Tracks the `develop` branch of this repo and is built using the [Dockerfile](Dockerfile) in this repo.

For more details on the Docker images, see the [`praekeltfoundation/docker-marathon-acme`](https://github.com/praekeltfoundation/docker-marathon-acme) repo.

##### Volumes and ports
The `marathon-acme` container defaults to the `/var/lib/marathon-acme` directory to store certificates and the ACME client private key. This is the path inside the container that should be mounted as a shared volume.

The container also defaults to listening on port 8000 on all interfaces.

You can override these values by providing arguments to the Docker container.

#### Certificate files
`marathon-acme` creates the following directory/file structure:
* `/var/lib/marathon-acme/`
  * `client.key`: The ACME client private key
  * `default.pem`: A self-signed wildcard cert for HAProxy to fallback to
  * `certs/`
    * _`www.example.com.pem`_: An issued ACME certificate for a domain
  * `unmanaged-certs/`: A directory for certs that `marathon-acme` doesn't manage

`marathon-acme` does nothing with the `unmanaged-certs/` directory after creating it. HAProxy fails if any path in its certificate config doesn't exist, so it reduces setup friction to have a standard place to put unmanaged certificates.

### `marathon-lb` configuration
`marathon-acme` requires `marathon-lb` 1.4.0 or later in order to be able to trigger HAProxy reloads.

As mentioned earlier, `marathon-lb` must share persistent storage with `marathon-acme`. BYONS: _bring your own networked storage._

The only real configuration needed for `marathon-lb` is to add the path to `marathon-acme`'s certificate storage directory as a source of certificates. HAProxy supports loading certificates from a directory. You should set `marathon-lb`'s `--ssl-certs` CLI option to the certificate directory path as well as the fallback certificate (if HAProxy cannot find any certificates in the paths it is given it will fail to start).
```
--ssl-certs <storage-dir>/certs,<storage-dir>/default.pem
```

### App configuration
`marathon-acme` uses a single `marathon-lb`-like label to assign domains to app ports: `MARATHON_ACME_{n}_DOMAIN`, where `{n}` is the port index. The value of the label is a set of comma- and/or whitespace-separated domain names, although **by default only the first domain name will be considered**.

Currently, `marathon-acme` can only issue certificates with a single domain. This means multiple certificates need to be issued for apps with multiple configured domains.

A limitation was added that limits apps to a single domain. This limit can be removed by passing the `--allow-multiple-certs` command-line option, although this is not recommended as it makes it possible for a large number of certificates to be issued for a single app, potentially exhausting the Let's Encrypt rate limit.

The app or its port must must be in the same `HAPROXY_GROUP` as `marathon-acme` was configured with at start-up.

We decided not to reuse the `HAPROXY_{n}_VHOST` label so as to limit the number of domains that certificates are issued for.

## Limitations
The library used for ACME certificate management, `txacme`, is currently quite limited in its functionality. The two biggest limitations are:
* There is no [Subject Alternative Name](https://en.wikipedia.org/wiki/Subject_Alternative_Name) (SAN) support yet ([#37](https://github.com/mithrandi/txacme/issues/37)). Each certificate will correspond to exactly one domain name. This limitation makes it easier to hit Let's Encrypt's rate limits.
* There is no support for *removing* certificates from `txacme`'s certificate store ([#77](https://github.com/mithrandi/txacme/issues/77)). Once `marathon-acme` issues a certificate for an app it will try to renew that certificate *forever* unless it is manually deleted from the certificate store.

For a more complete list of issues, see the issues page for this repo.

## Troubleshooting
### Challenge ping endpoint
One common problem is that `marathon-lb` is misconfigured and ACME challenge requests are unable to reach `marathon-acme`. You can test challenge request routing to `marathon-acme` using the challenge ping endpoint.

It should be possible to reach the  `/.well-known/acme-challenge/ping` path from all domains served by `marathon-lb`:
```
> $ curl cake-service.example.com/.well-known/acme-challenge/ping
{"message": "pong"}

> $ curl soda-service.example.com/.well-known/acme-challenge/ping
{"message": "pong"}
```
