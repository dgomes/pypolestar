"""Python API for Polestar Connected API. """

from datetime import datetime, timedelta
import json
import logging
import aiohttp

from urllib.parse import parse_qs, urlparse

from .const import (
    CACHE_TIME,
)
from .exceptions import PolestarApiException
from .auth import PolestarAuth

POST_HEADER_JSON = {"Content-Type": "application/json"}

_LOGGER = logging.getLogger(__name__)


class PolestarApi:

    def __init__(self, session, username: str, password: str):
        self.username = username
        self.password = password
        self._session = session or aiohttp.ClientSession()
        self.auth = PolestarAuth(self._session, self.username, self.password)

    async def init(self):
        await self.auth.get_token()

        result = await self.get_vehicle_data()

        # check if there are cars in the account
        if result['data']['getConsumerCarsV2'] is None or len(result['data']['getConsumerCarsV2']) == 0:
            _LOGGER.error("No cars found in account")
            raise PolestarApiException("No cars found in account")

        self.cache_data['getConsumerCarsV2'] = {
            'data': result['data']['getConsumerCarsV2'][0], 'timestamp': datetime.now()}

        # fill the vin and id in the constructor
        self.vin = result['data']['getConsumerCarsV2'][0]['vin']
        self.id = self.vin[:8]
        self.name = "Polestar " + self.vin[-4:]

    def get_latest_data(self, query: str, field_name: str) -> dict or bool or None:
        if self.cache_data and self.cache_data[query]:
            data = self.cache_data[query]['data']
            if data is None:
                return False
            return self._get_field_name_value(field_name, data)

    def _get_field_name_value(self, field_name: str, data: dict) -> str or bool or None:
        if field_name is None:
            return None

        if data is None:
            return None

        if '/' in field_name:
            field_name = field_name.split('/')
        if data:
            if isinstance(field_name, list):
                for key in field_name:
                    if data.get(key):
                        data = data[key]
                    else:
                        return None
                return data
            return data[field_name]
        return None

    def get_cache_data(self, query: str, field_name: str, skip_cache: bool = False):
        if query is None:
            return None

        if self.cache_data and self.cache_data.get(query):
            if skip_cache is False:
                if self.cache_data[query]['timestamp'] + timedelta(seconds=CACHE_TIME) > datetime.now():
                    data = self.cache_data[query]['data']
                    if data is None:
                        return None
                    return self._get_field_name_value(field_name, data)
            else:
                data = self.cache_data[query]['data']
                if data is None:
                    return None
                return self._get_field_name_value(field_name, data)
        return None

    async def getOdometerData(self):
        result = await self.get_odo_data()
        # put result in cache
        self.cache_data['getOdometerData'] = {
            'data': result['data']['getOdometerData'], 'timestamp': datetime.now()}

    async def getBatteryData(self):
        result = await self.get_battery_data()
        # put result in cache
        self.cache_data['getBatteryData'] = {
            'data': result['data']['getBatteryData'], 'timestamp': datetime.now()}

    async def get_ev_data(self):
        if self.updating is True:
            return
        self.updating = True
        await self.getOdometerData()
        await self.getBatteryData()
        self.updating = False

    async def get_graph_ql(self, params: dict):
        headers = await self.auth.headers()

        result = await self._session.get("https://pc-api.polestar.com/eu-north-1/my-star/", params=params, headers=headers)
        resultData = await result.json()

        # if auth error, get new token
        if resultData.get('errors'):
            if resultData['errors'][0]['message'] == 'User not authenticated':
                await self.get_token()
                resultData = await self.get_graph_ql(params)
            else:
                # log the error
                _LOGGER.warning(resultData.get('errors'))
        _LOGGER.debug(resultData)
        return resultData

    async def get_odo_data(self):
        # get Odo Data
        params = {
            "query": "query GetOdometerData($vin: String!) { getOdometerData(vin: $vin) { averageSpeedKmPerHour eventUpdatedTimestamp { iso unix __typename } odometerMeters tripMeterAutomaticKm tripMeterManualKm __typename }}",
            "operationName": "GetOdometerData",
            "variables": "{\"vin\":\"" + self.vin + "\"}"
        }
        return await self.get_graph_ql(params)

    async def get_battery_data(self):
        # get Battery Data
        params = {
            "query": "query GetBatteryData($vin: String!) {  getBatteryData(vin: $vin) {    averageEnergyConsumptionKwhPer100Km    batteryChargeLevelPercentage    chargerConnectionStatus    chargingCurrentAmps    chargingPowerWatts    chargingStatus    estimatedChargingTimeMinutesToTargetDistance    estimatedChargingTimeToFullMinutes    estimatedDistanceToEmptyKm    estimatedDistanceToEmptyMiles    eventUpdatedTimestamp {      iso      unix      __typename    }    __typename  }}",
            "operationName": "GetBatteryData",
            "variables": "{\"vin\":\"" + self.vin + "\"}"
        }
        return await self.get_graph_ql(params)

    async def get_vehicle_data(self):
        # get Vehicle Data
        params = {
            "query": "query getCars {  getConsumerCarsV2 {    vin    internalVehicleIdentifier    modelYear    content {      model {        code        name        __typename      }      images {        studio {          url          angles          __typename        }        __typename      }      __typename    }    hasPerformancePackage    registrationNo    deliveryDate    currentPlannedDeliveryDate    __typename  }}",
            "operationName": "getCars",
            "variables": "{}"
        }
        return await self.get_graph_ql(params)

    def __version__(self):
        return "0.1.0"