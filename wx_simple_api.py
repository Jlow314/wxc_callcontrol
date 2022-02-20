"""
Simple API implementing the Webex API endpoint required for the Webex Calling call control demo bot
"""
import base64
import datetime
import json
import logging
import time
import urllib.parse
import uuid
from enum import Enum
from io import StringIO, TextIOBase
from typing import Optional, List, Literal, Type, Tuple, Union

import backoff
import requests
from pydantic import BaseModel, Field
from pydantic import ValidationError
from requests import Session, HTTPError, Response

from tokens import Tokens

__all__ = ['WebexSimpleApi', 'Person', 'CallType', 'RedirectReason', 'RecordingState', 'Personality', 'CallState',
           'TelephonyEvent', 'WebHookEvent', 'WebHookResource', 'WebHook', 'RestError', 'dump_response']

log = logging.getLogger(__name__)


def webex_id_to_uuid(webex_id: Optional[str]) -> Optional[str]:
    """
    Convert a webex id as used by the public APIs to a UUID
    :param webex_id:
    :return:
    """
    return webex_id and base64.b64decode(f'{webex_id}==').decode().split('/')[-1]


class ApiChild:
    """
    Base class for child APIs of :class:'.WebexSimpleAPI'
    """

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
        alias_generator = to_camel  # alias is camelcase version of attribute name
        allow_population_by_field_name = True
        extra = 'allow'
        # set to forbid='forbid' to raise exceptions on schema error

    def json(self, *args, exclude_unset=True, by_alias=True, **kwargs) -> str:
        return super().json(*args, exclude_unset=exclude_unset, by_alias=by_alias, **kwargs)


class PhoneNumberType(str, Enum):
    """
    Webex phone number type
    """
    work = 'work'
    mobile = 'mobile'
    fax = 'fax'
    work_extension = 'work_extension'


class PhoneNumber(ApiModel):
    """
    Webex phone number: type and Value
    """
    number_type: PhoneNumberType = Field(alias='type')
    value: str


class SipType(str, Enum):
    """
    SIP address type
    """
    enterprise = 'enterprise'
    cloudCalling = 'cloud-calling'
    personalRoom = 'personal-room'
    unknown = 'unknown'


class SipAddress(ApiModel):
    """
    SIP address: type, value and primary indication
    """
    sip_type: SipType = Field(alias='type')
    value: str
    primary: bool


class Person(ApiModel):
    """
    Webex person
    """
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
    """
    Webex Calling call types
    """
    location = 'location'
    organization = 'organization'
    external = 'external'
    emergency = 'emergency'
    repair = 'repair'
    other = 'other'


class TelephonyEventParty(ApiModel):
    """
    Representation of a calling/called party of a Webex Calling call
    """
    name: Optional[str]
    number: str
    person_id: Optional[str]
    place_id: Optional[str]
    privacy_enabled: str
    call_type: CallType


class RedirectReason(str, Enum):
    """
    reason for Call redirection
    """
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
    """
    Single redirection
    """
    reason: RedirectReason
    redirecting_party: TelephonyEventParty


class Recall(ApiModel):
    """
    call recall
    """
    recall_type: str = Field(alias='type')
    party: TelephonyEventParty


class RecordingState(str, Enum):
    """
    recording state of a Webex Calling call
    """
    pending = 'pending'
    started = 'started'
    paused = 'paused'
    stopped = 'stopped'
    failed = 'failed'


class Personality(str, Enum):
    """
    Roles of an entity in a Webex Calling call
    """
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


class TelephonyCall(ApiModel):
    """
    Representation of a Webex Calling call
    """
    # In events the property is "callId"
    id_call_id: Optional[str] = Field(alias='callId')
    # ..while the telephony API uses "id"
    id_id: Optional[str] = Field(alias='id')

    # .. but this should handle that
    @property
    def call_id(self) -> Optional[str]:
        return self.id_id or self.id_call_id

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


class TelephonyEventData(TelephonyCall):
    event_type: str
    event_timestamp: datetime.datetime


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
    """
    API endppont for webhook management
    """

    def list(self) -> List[WebHook]:
        ep = self.ep('webhooks')
        result = self._api.follow_pagination(url=ep, model=WebHook)
        return result

    def create(self, *, name: str, target_url: str, resource: WebHookResource, event: WebHookEvent, filter: str = None,
               secret: str = None,
               owned_by: str = None) -> WebHook:
        """
        Creates a webhook.
        :param name: A user-friendly name for the webhook.
        :type name: str
        :param target_url: The URL that receives POST requests for each event.
        :type target_url: str
        :param resource:The resource type for the webhook. Creating a webhook requires 'read' scope on the resource
            the webhook is for.
        :type resource: WebHookResource
        :param event: The event type for the webhook.
        :type event: WebHookEvent
        :param filter: The filter that defines the webhook scope.
        :type filter: str
        :param secret: The secret used to generate payload signature.
        :type secret: str
        :param owned_by: Specified when creating an org/admin level webhook. Supported for meetings, recordings and
            meetingParticipants resources for now.
        :type owned_by: str
        :return: the new webhook
        :rtype:WebHook
        """
        params = {to_camel(param): value for i, (param, value) in enumerate(locals().items())
                  if i and value is not None}
        body = json.loads(WebHookCreate(**params).json())
        ep = self.ep('webhooks')
        data = self._api.post(ep, json=body)
        result = WebHook.parse_obj(data)
        return result

    def webhook_delete(self, *, webhook_id: str):
        """
        Deletes a webhook, by ID.
        :param webhook_id: The unique identifier for the webhook.
        :type webhook_id: str
        :return: None
        :rtype: Noone
        """
        ep = self.ep(f'webhooks/{webhook_id}')
        self._api.delete(ep)


class SingleError(BaseModel):
    description: str
    code: int


class ErrorDetail(ApiModel):
    """
    Representation of error details in the body of an HTTP error response from Wenex Calling
    """
    message: str
    errors: List[SingleError]
    tracking_id: str

    @property
    def description(self) -> str:
        return self.errors and self.errors[0].description or ''

    @property
    def code(self) -> int:
        return self.errors and self.errors[0].code or 0


class RestError(HTTPError):
    """
    A REST error. Sub class of :class:HTTPError
    """

    def __init__(self, msg: str, response: requests.Response):
        super().__init__(msg, response=response)
        # try to parse the body of the API response
        try:
            self.detail = ErrorDetail.parse_obj(json.loads(response.text))
        except (json.JSONDecodeError, ValidationError):
            self.detail = None

    @property
    def description(self) -> str:
        return self.detail and self.detail.description or ''

    @property
    def code(self) -> str:
        return self.detail and self.detail.code or 0


def giveup_429(e: RestError) -> bool:
    """
    callback for backoff on REST requests
    :param e: latest exception
    :type e: RestError
    :return: True -> break the backoff loop
    :rtype: bool
    """
    response = e.response
    response: Response
    if response.status_code != 429:
        # Don't retry on anything other than 429
        return True

    # determine how long we have to wait
    retry_after = int(response.headers.get('Retry-After', 5))

    # never wait more than the defined maximum
    retry_after = min(retry_after, 20)
    time.sleep(retry_after)
    return False


class DialResponse(ApiModel):
    """
    Result of call initiation using the dial() method
    """
    call_id: str
    call_session_id: str


class TelephonyAPI(ApiChild):
    """
    The telephony API. Child of :class:'.WebexSimpleApi'
    """

    def ep(self, path: str):
        return super().ep(f'telephony/{path}')

    def dial(self, destination: str) -> DialResponse:
        """
        Initiate an outbound call to a specified destination. This is also commonly referred to as Click to Call or
        Click to Dial. Alerts on all the devices belonging to the user. When the user answers on one of these alerting
        devices, an outbound call is placed from that device to the destination.
        :param destination: The destination to be dialed. The destination can be digits or a URI. Some examples for
            destination include: 1234, 2223334444, +12223334444, *73, tel:+12223334444, user@company.domain,
            sip:user@company.domain
        :type destination: str
        :return: Tuple of call id and call session id
        :rtype:
        """
        ep = self.ep('calls/dial')
        data = self._api.post(ep, json={'destination': destination})
        return DialResponse.parse_obj(data)

    def answer(self, call_id: str):
        """
        Answer an incoming call on the user's primary device.
        :param call_id: The call identifier of the call to be answered.
        :type call_id: str
        :return: None
        :rtype: None
        """
        ep = self.ep('calls/answer')
        self._api.post(ep, json={'callId': call_id})

    def hangup(self, call_id: str):
        """
        Hangup a call. If used on an unanswered incoming call, the call is rejected and sent to busy.
        :param call_id: The call identifier of the call to hangup.
        :type call_id: str
        :return: None
        :rtype: None
        """
        ep = self.ep('calls/hangup')
        self._api.post(ep, json={'callId': call_id})

    def list_calls(self) -> List[TelephonyCall]:
        """
        Get the list of details for all active calls associated with the user.
        :return: list of calls
        :rtype: List[TelephonyCall]
        """
        ep = self.ep('calls')
        calls = self._api.follow_pagination(url=ep, model=TelephonyCall)
        # noinspection PyTypeChecker
        return calls

    def call_details(self, call_id: str) -> TelephonyCall:
        """
        Get the details of the specified active call for the user.
        :param call_id: The call identifier of the call.
        :type call_id: str
        :return: call details
        :rtype: TelephonyCall
        """
        ep = self.ep(f'calls/{call_id}')
        data = self._api.get(ep)
        return TelephonyCall.parse_obj(data)


def dump_response(response: requests.Response, file: TextIOBase = None, dump_log: logging.Logger = None) -> None:
    """
    Dump response to log file
    :param response: HTTP request response
    :type response: request.Response
    :param file: stream to dump to
    :type file: TextIOBase
    :param dump_log: logger to dump to
    :type dump_log: logging.Logger
    :return: None
    :rtype: None
    """
    if not log.isEnabledFor(logging.DEBUG):
        return
    dump_log = dump_log or log
    output = file or StringIO()

    # dump response objects in redirect history
    for h in response.history:
        dump_response(response=h, file=output)

    print(f'Request {response.status_code}[{response.reason}]: '
          f'{response.request.method} {response.request.url}', file=output)

    # request headers
    for k, v in response.request.headers.items():
        if k == 'Authorization':
            v = 'Bearer ***'
        print(f'  {k}: {v}', file=output)

    # request body
    request_body = response.request.body
    if request_body:
        print('  --- body ---', file=output)
        ct = response.request.headers.get('content-type').lower()
        if ct.startswith('application/json'):
            for line in json.dumps(json.loads(request_body), indent=2).splitlines():
                print(f'  {line}', file=output)
        elif ct.startswith('application/x-www-form-urlencoded'):
            for k, v in urllib.parse.parse_qsl(request_body):
                print(f'  {k}: {v}', file=output)
        else:
            print(f'  {request_body}', file=output)

    print(f' Response', file=output)
    # response heders
    for k in response.headers:
        print(f'  {k}: {response.headers[k]}', file=output)
    body = response.text
    # dump response body
    if body:
        print('  ---response body ---', file=output)
        try:
            body = json.dumps(json.loads(body), indent=2)
        except json.JSONDecodeError:
            pass
        for line in body.splitlines():
            print(f'  {line}', file=output)
    print(f' ---- end ----', file=output)
    if file is None:
        dump_log.debug(output.getvalue())


class WebexSimpleApi:
    """
    A simple API implementing the endpoints needed for the simple demo
    """
    base = 'https://webexapis.com/v1'

    def ep(self, path: str) -> str:
        """
        endpoint URL
        :param path: path behind the API base URL
        :type path: str
        :return: URL for a given endpoint
        :rtype: str
        """
        return f'{self.base}/{path}'

    def __init__(self, tokens: Tokens):
        self._tokens = tokens
        self._session = Session()
        self.people = PeopleApi(api=self)
        self.webhook = WebhookApi(api=self)
        self.telephony = TelephonyAPI(api=self)

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @backoff.on_exception(backoff.constant, RestError, interval=0, giveup=giveup_429)
    def _request_w_response(self, method: str, *args, headers=None,
                            **kwargs) -> Tuple[requests.Response, Union[dict, str]]:
        """
        low level API REST request with support for 429 rate limiting
        :param method: HTTP method
        :type method: str
        :param args:
        :type args:
        :param headers: prepared headers for request
        :type headers: Optional[dict]
        :param kwargs: additional keyward args
        :type kwargs: dict
        :return: Tuple of response object and body. Body can be text or dict (parsed from JSON body)
        :rtype:
        """
        headers = headers or dict()
        headers.update({'Authorization': f'Bearer {self._tokens.access_token}',
                        'Content-type': 'application/json;charset=utf-8',
                        'TrackingID': f'WXC_SIMPLE_{uuid.uuid4()}'})
        with self._session.request(method, *args, headers=headers, **kwargs) as response:
            dump_response(response)
            try:
                response.raise_for_status()
            except HTTPError as error:
                # create a RestEror based on HTTP error
                error = RestError(error.args[0], response=error.response)
                raise error
            # get response body as text pr dict (parsed JSON)
            ct = response.headers.get('Content-Type')
            if not ct:
                data = ''
            elif ct.startswith('application/json') and response.text:
                data = response.json()
            else:
                data = response.text
        return response, data

    def _request(self, method: str, *args, **kwargs) -> Union[str, dict]:
        """
        low level API request only returning the body
        :param method: HTTP method
        :type method: str
        :param args:
        :type args:
        :param headers: prepared headers for request
        :type headers: Optional[dict]
        :param kwargs: additional keyward args
        :type kwargs: dict
        :return: body. Body can be text or dict (parsed from JSON body)
        :rtype: Unon
        """
        _, data = self._request_w_response(method, *args, **kwargs)
        return data

    def get(self, *args, **kwargs):
        """
        GET request
        :param args:
        :type args:
        :param kwargs:
        :type kwargs:
        :return:
        :rtype:
        """
        return self._request('GET', *args, **kwargs)

    def post(self, *args, **kwargs):
        """
        POST request
        :param args:
        :type args:
        :param kwargs:
        :type kwargs:
        :return:
        :rtype:
        """
        return self._request('POST', *args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        DELETE request
        :param args:
        :type args:
        :param kwargs:
        :type kwargs:
        :return:
        :rtype:
        """
        return self._request('DELETE', *args, **kwargs)

    def follow_pagination(self, *, url: str, model: Type[ApiModel]) -> List[ApiModel]:
        """
        Handling RFC5988 pagination of list requests
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
