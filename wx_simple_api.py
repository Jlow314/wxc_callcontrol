import base64
import datetime
import json
import logging
import time
from enum import Enum
from typing import Optional, List, Literal, Type, Union

import backoff
from pydantic import BaseModel, Field
from requests import Session, HTTPError, Response

from tokens import Tokens

__all__ = ['WebexSimpleApi', 'Person', 'CallType', 'RedirectReason', 'RecordingState', 'Personality', 'CallState',
           'TelephonyEvent', 'WebHookEvent', 'WebHookResource', 'WebHook']

log = logging.getLogger(__name__)


def webex_id_to_uuid(webex_id: Optional[str]) -> Optional[str]:
    """
    Convert a webex id as used by the public APIs to a UUID
    :param webex_id:
    :return:
    """
    return webex_id and base64.b64decode(f'{webex_id}==').decode().split('/')[-1]


class ApiChild:

    def __init__(self, api: 'WebexSimpleApi'):
        self._api = api

    def ep(self, path: str):
        return self._api.ep(path)


def to_camel(s: str) -> str:
    """
    Convert snake case variable name to camel case
    log_id='log_id'
 -> logId='logId'

    :param s:
    :return:
    """
    return ''.join(w.title() if i else w for i, w in enumerate(s.split('_')))


class ApiModel(BaseModel):
    """
    Base for all models used by the APIs
    """

    class Config:
        alias_generator = to_camel
        allow_population_by_field_name = True
        extra = allow = 'allow'
        # set to forbid='forbid' to raise exceptions on schema error

    def json(self, *args, exclude_unset=True, by_alias=True, **kwargs) -> str:
        return super().json(*args, exclude_unset=exclude_unset, by_alias=by_alias, **kwargs)


class PhoneNumberType(str, Enum):
    work = 'work'
    mobile = 'mobile'
    fax = 'fax'
    work_extension = 'work_extension'


class PhoneNumber(ApiModel):
    number_type: PhoneNumberType = Field(alias='type')
    value: str


class SipType(str, Enum):
    enterprise = 'enterprise'
    cloudCalling = 'cloud-calling'
    personalRoom = 'personal-room'
    unknown = 'unknown'


class SipAddress(ApiModel):
    sip_type: SipType = Field(alias='type')
    value: str
    primary: bool


class Person(ApiModel):
    display_name: Optional[str]
    user_name: Optional[str]
    person_id: str = Field(alias='id')
    emails: List[str]
    phone_numbers: Optional[List[PhoneNumber]]
    extension: Optional[str]
    location_id: Optional[str]
    sip_addresses: Optional[List[SipAddress]]
    nick_name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    avatar: Optional[str]
    org_id: str
    roles: Optional[List[str]]
    licenses: Optional[List[str]]
    created: str
    last_modified: str
    timezone: Optional[str]
    last_activity: Optional[str]
    status: Optional[str]
    invite_pending: Optional[bool]
    login_enabled: Optional[bool]
    type_: str = Field(alias='type')
    site_urls: Optional[List[str]]
    xmpp_federation_jid: Optional[str]
    errors: Optional[dict]

    @property
    def person_id_uuid(self) -> str:
        """
        person id in uuid format
        :return:
        """
        return webex_id_to_uuid(self.person_id)


class PeopleApi(ApiChild):
    def me(self) -> Person:
        ep = self.ep('people/me')
        data = self._api.get(ep)
        result = Person.parse_obj(data)
        return result


class CallType(str, Enum):
    location = 'location'
    organization = 'organization'
    external = 'external'
    emergency = 'emergency'
    repair = 'repair'
    other = 'other'


class TelephonyEventParty(ApiModel):
    name: str
    number: str
    person_id: Optional[str]
    place_id: Optional[str]
    privacy_enabled: str
    call_type: CallType


class RedirectReason(str, Enum):
    busy = 'busy'
    noAnswer = 'noAnswer'
    unavailable = 'unavailable'
    unconditional = 'unconditional'
    time_of_day = 'timeOfDay'
    divert = 'divert'
    followMe = 'followMe'
    hunt_group = 'huntGroup'
    call_queue = 'callQueue'
    unknown = 'unknown'


class Redirection(ApiModel):
    reason: RedirectReason
    redirecting_party: TelephonyEventParty


class Recall(ApiModel):
    recall_type: str = Field(alias='type')
    party: TelephonyEventParty


class RecordingState(str, Enum):
    pending = 'pending'
    started = 'started'
    paused = 'paused'
    stopped = 'stopped'
    failed = 'failed'


class Personality(str, Enum):
    originator = 'originator'
    terminator = 'terminator'
    click_to_dial = 'clickToDial'


class CallState(str, Enum):
    connecting = 'connecting'
    alerting = 'alerting'
    connected = 'connected'
    held = 'held'
    remoteHeld = 'remoteHeld'
    disconnected = 'disconnected'


class TelephonyEventData(ApiModel):
    event_type: str
    event_timestamp: datetime.datetime
    call_id: str
    call_session_id: str
    personality: Personality
    state: CallState
    remote_party: TelephonyEventParty
    appearance: Optional[int]
    created: datetime.datetime
    answered: Optional[datetime.datetime]
    redirections: List[Redirection] = Field(default_factory=list)
    recall: Optional[Recall]
    recording_state: Optional[RecordingState]
    disconnected: Optional[datetime.datetime]


class TelephonyEvent(ApiModel):
    event_id: str = Field(alias='id')
    name: str
    target_url: str
    resource: Literal['telephony_calls']
    event: str
    org_id: str
    created_by: str
    app_id: str
    owned_by: str
    status: str
    created: datetime.datetime
    actor_id: str
    data: TelephonyEventData


class WebHookEvent(str, Enum):
    created = 'created'
    updated = 'updated'
    deleted = 'deleted'
    started = 'started'
    ended = 'ended'
    joined = 'joined'
    left = 'left'
    all = 'all'


class WebHookResource(str, Enum):
    attachment_actions = 'attachmentActions'
    memberships = 'memberships'
    messages = 'messages'
    rooms = 'rooms'
    telephony_calls = 'telephony_calls'
    telephony_mwi = 'telephony_mwi'
    meetings = 'meetings'
    recordings = 'recordings'
    meeting_participants = 'meetingParticipants'
    meeting_transcripts = 'meetingTranscripts'


class WebHookCreate(ApiModel):
    name: str
    target_url: str
    resource: WebHookResource
    event: WebHookEvent
    filter: Optional[str]
    secret: Optional[str]
    owned_by: Optional[str]


class WebHook(ApiModel):
    webhook_id: str = Field(alias='id')
    name: str
    target_url: str
    resource: WebHookResource
    event: WebHookEvent
    org_id: str
    created_by: str
    app_id: str
    owned_by: str
    status: str
    created: datetime.datetime

    @property
    def app_id_uuid(self) -> str:
        return webex_id_to_uuid(self.app_id)

    @property
    def webhook_id_uuid(self) -> str:
        return webex_id_to_uuid(self.webhook_id)

    @property
    def org_id_uuid(self) -> str:
        return webex_id_to_uuid(self.org_id)

    @property
    def created_by_uuid(self) -> str:
        return webex_id_to_uuid(self.created_by)


class WebhookApi(ApiChild):
    def list(self) -> List[WebHook]:
        ep = self.ep('webhooks')
        result = self._api.follow_pagination(url=ep, model=WebHook)
        return result

    def create(self, *, name: str, target_url: str, resource: WebHookResource, event: WebHookEvent, filter: str = None,
               secret: str = None,
               owned_by: str = None):
        params = {to_camel(param): value for i, (param, value) in enumerate(locals().items())
                  if i and value is not None}
        body = json.loads(WebHookCreate(**params).json())
        ep = self.ep('webhooks')
        data = self._api.post(ep, json=body)
        result = WebHook.parse_obj(data)
        return result

    def webhook_delete(self, *, webhook_id: str):
        ep = self.ep(f'webhooks/{webhook_id}')
        self._api.delete(ep)


def giveup_429(e: HTTPError):
    response = e.response
    response: Response
    if response.status_code != 429:
        # Don't retry on anything other than 429
        return True
    retry_after = int(response.headers.get('Retry-After', 5))
    # never wait more than the defined maximum
    retry_after = min(retry_after, 20)
    time.sleep(retry_after)
    return False


class WebexSimpleApi:
    base = 'https://webexapis.com/v1'

    def ep(self, path: str):
        return f'{self.base}/{path}'

    def __init__(self, tokens: Tokens):
        self._tokens = tokens
        self._session = Session()
        self.people = PeopleApi(api=self)
        self.webhook = WebhookApi(api=self)

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @backoff.on_exception(backoff.constant, HTTPError, interval=0, giveup=giveup_429)
    def _request_w_response(self, method: str, *args, headers=None, **kwargs):
        headers = headers or dict()
        headers.update({'Authorization': f'Bearer {self._tokens.access_token}'})
        with self._session.request(method, *args, headers=headers, **kwargs) as response:
            response.raise_for_status()
            ct = response.headers.get('Content-Type')
            if not ct:
                data = ''
            elif ct.startswith('application/json'):
                data = response.json()
            else:
                data = response.text
        return response, data

    def _request(self, method: str, *args, **kwargs):
        _, data = self._request_w_response(method, *args, **kwargs)
        return data

    def get(self, *args, **kwargs):
        return self._request('GET',  *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._request('POST', *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._request('DELETE',  *args, **kwargs)

    def follow_pagination(self, *, url: str, model: Type[ApiModel]) -> List[ApiModel]:
        """
        Async iterator handling RFC5988 pagination of list requests
        :param url: start url for 1st GET
        :param model: data type to return
        :return: list object instances created by factory
        """
        result = []
        while url:
            log.debug(f'{self}.pagination: getting {url}')
            response, data = self._request_w_response('GET', url)
            # try to get the next page (if present)
            try:
                url = str(response.links['next']['url'])
            except KeyError:
                url = None
            # return all items
            items = data.get('items', [])
            result.extend(model.parse_obj(o) for o in items)

        return result
