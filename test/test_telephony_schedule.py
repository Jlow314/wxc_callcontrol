"""
Unit test for Schedules
"""
# TODO: testcase for event update
# TODO test case for event delete
# TODO test case for schedule delete
import datetime
import random
import re
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from itertools import chain
from typing import List, Union, Any, Optional

from base import TestCaseWithLog
from webex_simple_api.locations import *
from webex_simple_api.telephony.schedules import *


def gather(fs: List[Future], return_exceptions: bool = False) -> Generator[Union[Any, Exception]]:
    """
    Gather results from a list of futures; similar to asyncio.gather
    :param fs: list of futures
    :type fs: List[Future]
    :param return_exceptions: True: return exceptions; False: exceptions are raised
    :return: List of results
    """
    r = []
    for future in fs:
        try:
            yield future.result()
        except Exception as e:
            if return_exceptions:
                yield e
            else:
                raise e


@dataclass(init=False)
class TestWithLocations(TestCaseWithLog):
    """
    Test cases with existing locations
    """
    locations: List[Location]

    @classmethod
    def setUpClass(cls) -> None:
        """
        Get list of locations
        """
        super().setUpClass()
        if cls.api is None:
            cls.locations = None
            return
        cls.locations = list(cls.api.locations.list())

    def setUp(self) -> None:
        """
        Check if we have locations, Skip test if we don't have locations
        """
        super().setUp()
        if not self.locations:
            self.skipTest('Need at least ohe location to run test.')


class TestScheduleList(TestWithLocations):
    """
    Test cases for schedules
    """

    def all_schedules(self) -> List[Schedule]:
        """
        Get all existing schedules in all locations
        :return: list of schedules
        """
        with ThreadPoolExecutor() as pool:
            tasks = [pool.submit(list, self.api.telephony.schedules.list(location_id=location.location_id))
                     for location in self.locations]
            schedules = list(chain.from_iterable(gather(tasks)))
        return schedules

    def test_001_list(self):
        """
        Try to list all existing schedules in all locations
        """
        schedules = self.all_schedules()
        print(f'got {len(schedules)} schedules')
        print('\n'.join(f'{s}' for s in schedules))

    def test_002_list_name(self):
        """
        Try to list by name
        """
        with ThreadPoolExecutor() as pool:
            tasks = [pool.submit(list, self.api.telephony.schedules.list(location_id=location.location_id,
                                                                         name='Germany 2'))
                     for location in self.locations]
            schedules = list(chain.from_iterable(gather(tasks)))
        schedules: List[Schedule]
        print(f'got {len(schedules)} schedules')
        print('\n'.join(f'{s}' for s in schedules))
        self.assertTrue(all(schedule.name.startswith('Germany 2') for schedule in schedules),
                        'Not all schedule names start with the expected string')

    def test_003_list_business_hours(self):
        """
        List all business hours schedules in all locations
        """
        with ThreadPoolExecutor() as pool:
            tasks = [pool.submit(list, self.api.telephony.schedules.list(location_id=location.location_id,
                                                                         schedule_type=ScheduleType.business_hours))
                     for location in self.locations]
            schedules = list(chain.from_iterable(gather(tasks)))
        schedules: List[Schedule]
        print(f'got {len(schedules)} schedules')
        print('\n'.join(f'{s}' for s in schedules))
        self.assertTrue(all(schedule.schedule_type == ScheduleType.business_hours for schedule in schedules),
                        'Schedule tyoe mismatch')

    def test_004_all_detail(self):
        """
        Get details of all schedules
        """
        schedules = self.all_schedules()
        with ThreadPoolExecutor() as pool:
            tasks = [pool.submit(self.api.telephony.schedules.details, **schedule.selector)
                     for schedule in schedules]
            details = list(gather(tasks))
        # no tests: we actually only want to test if there are any issues with parsing existing schedules

    def test_005_all_event_details(self):
        """
        Get all event details of all schedules
        """
        schedules = self.all_schedules()

        def schedule_event_details(schedule: Schedule):
            """
            get details of all events in given schedule
            :param schedule: schedule
            :type schedule: Schedule
            :return: list of schedules
            """
            details = self.api.telephony.schedules.details(
                location_id=schedule.location_id,
                schedule_type=schedule.schedule_type,
                schedule_id=schedule.schedule_id)
            details: Schedule
            if not details.events:
                return list()
            with ThreadPoolExecutor() as pool:
                tasks = [pool.submit(self.api.telephony.schedules.event_details,
                                     location_id=schedule.location_id,
                                     schedule_type=schedule.schedule_type,
                                     schedule_id=schedule.schedule_id,
                                     event_id=event.event_id)
                         for event in details.events]
                event_details = list(gather(tasks))
            return event_details

        with ThreadPoolExecutor() as pool:
            tasks = [pool.submit(schedule_event_details, schedule) for schedule in schedules]
            event_details = list(chain.from_iterable(gather(tasks)))
        print(f'Got details of {len(event_details)} events in {len(schedules)} schedules.')


@dataclass(init=False)
class TestWithTestSchedules(TestWithLocations):
    """
    Base class for tests with test schedules (test_xxx)
    """
    test_schedules: Optional[List[Schedule]]

    @classmethod
    def setUpClass(cls) -> None:
        """
        get all test_xxx schedules in all locations
        :return:
        """
        super().setUpClass()
        if not cls.locations:
            cls.test_schedules = None
            return
        with ThreadPoolExecutor() as pool:
            tasks = [pool.submit(list, cls.api.telephony.schedules.list(location_id=location.location_id,
                                                                        name='test_'))
                     for location in cls.locations]
            cls.test_schedules = list(chain.from_iterable(gather(tasks)))
        cls.test_schedules: List[Schedule]
        cls.test_schedules = [schedule
                              for schedule in cls.test_schedules
                              if re.match(r'test_\d{3}', schedule.name)]


class TestCreate(TestWithTestSchedules):
    """
    Test cases for schedule creation
    """

    def test_001_create_business(self):
        """
        create a business schedule in a random location
        """
        # select a random location
        target_location = random.choice(self.locations)
        print(f'Target location: "{target_location.name}"')

        schedules = list(self.api.telephony.schedules.list(location_id=target_location.location_id))
        schedule_names = set(sched.name for sched in schedules)
        schedule_name = next((name for i in range(1000)
                              if (name := f'test_{i:03d}') not in schedule_names))
        schedule = Schedule.business(name=schedule_name)
        schedule_id = self.api.telephony.schedules.create(location_id=target_location.location_id, schedule=schedule)
        details = self.api.telephony.schedules.details(location_id=target_location.location_id,
                                                       schedule_type=schedule.schedule_type,
                                                       schedule_id=schedule_id)
        print(f'created schedule: {target_location.name}/{schedule_name}/{id}')
        self.assertEqual(len(schedule.events), len(details.events))
        self.assertEqual(schedule.name, details.name)

    def test_002_create_event(self):
        """
        create an event
        """
        if not self.test_schedules:
            self.skipTest('Need at least one test schedule (test_xxx)')

        target_schedule = random.choice(self.test_schedules)
        details = self.api.telephony.schedules.details(**target_schedule.selector)
        # add an event
        event_names = set(event.name for event in details.events)
        event_name = next(name for i in range(1000)
                          if (name := f'today_{i:03d}') not in event_names)
        event = Event(name=event_name,
                      all_day_enabled=True,
                      start_date=datetime.date.today(),
                      end_date=datetime.date.today(),
                      recurrence=Recurrence(recur_for_ever=True,
                                            recur_yearly_by_date=RecurYearlyByDate.from_date(datetime.date.today())))
        event_id = self.api.telephony.schedules.event_create(**target_schedule.selector,
                                                             event=event)
        details_after = self.api.telephony.schedules.details(**target_schedule.selector)
        self.assertEqual(len(details.events) + 1, len(details_after.events))
        self.assertEqual(event_name, details_after.events[-1].name)
        self.assertEqual(event_id, details_after.events[-1].event_id)


class TestUpdateSchedule(TestWithTestSchedules):
    """
    Test cases for updating schedules
    """

    def setUp(self) -> None:
        super().setUp()
        if not self.test_schedules:
            self.skipTest('Need at least one test schedule (test_xxx)')

    def test_001_update_schedule_name(self):
        """
        test to update a schedule name
        """
        target_schedule = random.choice(self.test_schedules)
        details = self.api.telephony.schedules.details(**target_schedule.selector)
        schedule_names = set(schedule.name
                             for schedule in self.test_schedules
                             if schedule.location_id == target_schedule.location_id)
        old_name = target_schedule.name
        new_name = next(name for i in range(1000)
                        if (name := f'test_{i:03d}') not in schedule_names)
        details.name = new_name

        new_id = self.api.telephony.schedules.update(schedule=details, **target_schedule.selector)
        after = self.api.telephony.schedules.details(location_id=target_schedule.location_id,
                                                     schedule_type=target_schedule.schedule_type,
                                                     schedule_id=new_id)
        # restore old name
        details.name = old_name
        self.api.telephony.schedules.update(schedule=details,
                                            location_id=target_schedule.location_id,
                                            schedule_type=target_schedule.schedule_type,
                                            schedule_id=new_id)

        self.assertEqual(new_name, after.name)
        self.assertEqual(details.events, after.events)

    def test_002_update_event_names(self):
        """
        test to update event names
        """
        target_schedule = random.choice(self.test_schedules)
        # get details; we need the eventy
        details = self.api.telephony.schedules.details(**target_schedule.selector)

        # change all event names: add a leading 'U'
        update = details.copy(deep=True)
        for event in update.events:
            event.new_name = f'U{event.name}'
        new_id = self.api.telephony.schedules.update(schedule=update, **target_schedule.selector)
        after = self.api.telephony.schedules.details(location_id=target_schedule.location_id,
                                                     schedule_type=target_schedule.schedule_type,
                                                     schedule_id=new_id)

        # restore old settings
        restore = update.copy(deep=True)
        # update names back to original: swap new name and name for each event
        for event in restore.events:
            event.name, event.new_name = event.new_name, event.name
        self.api.telephony.schedules.update(schedule=restore,
                                            location_id=target_schedule.location_id,
                                            schedule_type=target_schedule.schedule_type,
                                            schedule_id=new_id)
        # number of events should not have changed
        self.assertEqual(len(details.events), len(after.events))

        # schedule should not have changed with the exception of events
        self.assertEqual(details.json(exclude={'events'}), after.json(exclude={'events'}))

        # for each event
        #   * name should have changed
        #   * everything else should be unchanged
        for event, after_event in zip(details.events, after.events):
            self.assertEqual(f'U{event.name}', after_event.name)
            # all event settings with the exception of event_id and name should be identical
            event_json = event.json(exclude={'event_id', 'name'})
            after_event_json = after_event.json(exclude={'event_id', 'name'})
            self.assertEqual(event_json, after_event_json)
