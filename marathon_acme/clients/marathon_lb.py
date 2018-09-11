from twisted.internet.defer import DeferredList
from twisted.logger import LogLevel

from marathon_acme.clients._base import HTTPClient, raise_for_status


class MarathonLbClient(HTTPClient):
    """
    Very basic client for accessing the ``/_mlb_signal`` endpoints on
    marathon-lb.
    """

    def __init__(self, endpoints, *args, **kwargs):
        """
        :param endpoints:
            The list of marathon-lb endpoints. All marathon-lb endpoints will
            be called at once for any request.
        """
        super(MarathonLbClient, self).__init__(*args, **kwargs)
        self.endpoints = endpoints

    def request(self, *args, **kwargs):
        return (
            DeferredList(
                [self._request(e, *args, **kwargs) for e in self.endpoints],
                consumeErrors=True)
            .addCallback(self._check_request_results))

    def _request(self, endpoint, *args, **kwargs):
        """
        Perform a request to a specific endpoint. Raise an error if the status
        code indicates a client or server error.
        """
        kwargs['url'] = endpoint
        return (super(MarathonLbClient, self).request(*args, **kwargs)
                .addCallback(raise_for_status))

    def _check_request_results(self, results):
        """
        Check the result of each request that we made. If a failure occurred,
        but some requests succeeded, log and count the failures. If all
        requests failed, raise an error.

        :return:
            The list of responses, with a None value for any requests that
            failed.
        """
        responses = []
        failed_endpoints = []
        for index, result_tuple in enumerate(results):
            success, result = result_tuple
            if success:
                responses.append(result)
            else:
                endpoint = self.endpoints[index]
                self.log.failure(
                    'Failed to make a request to a marathon-lb instance: '
                    '{endpoint}', result, LogLevel.error, endpoint=endpoint)
                responses.append(None)
                failed_endpoints.append(endpoint)

        if len(failed_endpoints) == len(self.endpoints):
            raise RuntimeError(
                'Failed to make a request to all marathon-lb instances')

        if failed_endpoints:
            self.log.error(
                'Failed to make a request to {x}/{y} marathon-lb instances: '
                '{endpoints}', x=len(failed_endpoints), y=len(self.endpoints),
                endpoints=failed_endpoints)

        return responses

    def mlb_signal_hup(self):
        """
        Trigger a SIGHUP signal to be sent to marathon-lb. Causes a full reload
        of the config as though a relevant event was received from Marathon.
        """
        return self.request('POST', path='/_mlb_signal/hup')

    def mlb_signal_usr1(self):
        """
        Trigger a SIGUSR1 signal to be sent to marathon-lb. Causes the existing
        config to be reloaded, whether it has changed or not.
        """
        return self.request('POST', path='/_mlb_signal/usr1')
