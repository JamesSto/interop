"""Missions view."""

import json
import logging
from auvsi_suas.models import MissionConfig, GpsPosition, AerialPosition, Waypoint
from auvsi_suas.views import logger
from auvsi_suas.views.decorators import require_login
from auvsi_suas.views.decorators import require_superuser
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseNotFound
from django.http import HttpResponseServerError
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.generic import View


def active_mission():
    """Gets the single active mission.

    Returns:
        (MissionConfig, HttpResponse). The MissionConfig is the single active
        mission, or None if there is an error. HttpResponse is None if a config
        could be obtained, or the error message if not.
    """
    # First check cache.
    active_mission_key = '/MissionConfig/active_mission'
    active_mission = cache.get(active_mission_key)
    if active_mission:
        return (active_mission, None)

    # Active mission not cached, query for one.
    missions = MissionConfig.objects.filter(is_active=True)
    if len(missions) != 1:
        logging.warning('Invalid number of active missions. Missions: %s.',
                        str(missions))
        return (None,
                HttpResponseServerError('Invalid number of active missions.'))

    # Add to cache for future requests.
    active_mission = missions[0]
    cache.set(active_mission_key, active_mission)

    return (active_mission, None)


def mission_for_request(request_params):
    """Gets the mission for the request.

    Args:
        request_params: The request parameter dict. If this has a 'mission'
            parameter, it will get the corresponding mission.
    Returns:
        Returns (MissionConfig, HttpResponse). The MissionConfig is
        the one corresponding to the request parameter, or the single active
        MissionConfig if one exists. The HttpResponse is the appropriate error
        if a MissionConfig could not be obtained.
    """
    # If specific mission requested, get it.
    if 'mission' in request_params:
        try:
            mission_id_str = request_params['mission']
            mission_id = int(mission_id_str)
            mission = MissionConfig.objects.get(pk=mission_id)
            return (mission, None)
        except ValueError:
            logging.warning('Invalid mission ID given. ID: %d.',
                            mission_id_str)
            return (None,
                    HttpResponseBadRequest('Mission ID is not an integer.'))
        except MissionConfig.DoesNotExist:
            logging.warning('Given mission ID not found. ID: %d.', mission_id)
            return (None, HttpResponseBadRequest('Mission not found.'))

    # Mission not specified, get the single active mission.
    return active_mission()


class MissionSetWaypoints(View):
    @method_decorator(require_superuser)
    def post(self, request):
        try:
            sent_json = json.loads(request.body)
        except ValueError:
            return HttpResponseBadRequest('Body is not a valid json')

        try:
            pk = sent_json['pk']
            waypoints = sent_json['waypoints']
            assert type(pk) == int
            assert type(waypoints) == list
            assert all(type(w) == dict and 'latitude' in w and
                       'longitude' in w and 'altitude_msl' in w
                       for w in waypoints)
        except (KeyError, AssertionError):
            return HttpResponseBadRequest(
                'JSON does not contain properly formatted fields')

        try:
            # if the pk is 0, edit the currently active mission
            if pk == 0:
                active = active_mission()
                if active[0] == None:
                    return active[1]
                else:
                    mission = active[0]
            else:
                mission = MissionConfig.objects.get(pk=pk)
        except MissionConfig.DoesNotExist:
            return HttpResponseNotFound('Mission %s not found.' % pk)

        waypoints_objects = []
        for i, waypoint in enumerate(waypoints):
            gps_position = GpsPosition.objects.create(
                latitude=waypoint['latitude'],
                longitude=waypoint['longitude'])

            aerial_position = AerialPosition.objects.create(
                gps_position=gps_position,
                altitude_msl=waypoint['altitude_msl'])

            new_wp_object = Waypoint.objects.create(position=aerial_position,
                                                    order=(i + 1))

            waypoints_objects.append(new_wp_object)

        mission.mission_waypoints = waypoints_objects
        mission.save()
        return HttpResponse("Successfully changed mission waypoints")


class Missions(View):
    """Handles requests for all missions."""

    @method_decorator(require_login)
    def dispatch(self, *args, **kwargs):
        return super(Missions, self).dispatch(*args, **kwargs)

    def get(self, request):
        missions = MissionConfig.objects.all()
        out = []
        for mission in missions:
            out.append(mission.json(request.user.is_superuser))

        # Older versions of JS allow hijacking the Array constructor to steal
        # JSON data. It is not a problem in recent versions.
        return JsonResponse(out, safe=False)


class MissionsId(View):
    """Handles requests for a specific mission."""

    @method_decorator(require_login)
    def dispatch(self, *args, **kwargs):
        return super(MissionsId, self).dispatch(*args, **kwargs)

    def get(self, request, pk):
        try:
            mission = MissionConfig.objects.get(pk=pk)
            return JsonResponse(mission.json(request.user.is_superuser))
        except MissionConfig.DoesNotExist:
            return HttpResponseNotFound('Mission %s not found.' % pk)
