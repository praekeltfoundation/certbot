def get_number_of_app_ports(app):
    """
    Get the number of ports for the given app JSON. This roughly follows the
    logic in marathon-lb for finding app IPs/ports, although we are only
    interested in the quantity of ports an app has:
    https://github.com/mesosphere/marathon-lb/blob/v1.7.0/utils.py#L278-L350

    :param app: The app JSON from the Marathon API.
    :return: The number of ports for the app.
    """
    if _is_ip_per_task(app):
        if _is_user_network(app):
            return len(app['container']['docker']['portMappings'])
        else:
            return len(app['ipAddress']['discovery']['ports'])
    else:
        # Prefer the 'portDefinitions' field added in Marathon 1.0.0 but fall
        # back to the deprecated 'ports' array if that's not present.
        if 'portDefinitions' in app:
            return len(app['portDefinitions'])
        else:
            return len(app['ports'])


def _is_ip_per_task(app):
    """
    Return whether the application is using IP-per-task.
    :param app: The application to check.
    :return: True if using IP per task, False otherwise.
    """
    return app.get('ipAddress') is not None


def _is_user_network(app):
    """
    Returns True if container network mode is set to USER
    :param app: The application to check.
    :return: True if using USER network, False otherwise.
    """
    container = app.get('container')
    if container is None:
        return False

    if container['type'] != 'DOCKER':
        return False

    return container['docker']['network'] == 'USER'
