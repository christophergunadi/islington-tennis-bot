import asyncio
import json
import logging
import os
import traceback
from datetime import datetime, timedelta

import requests
import telegram
from dotenv import load_dotenv

MONDAY = 0
TUESDAY = 1
WEDNESDAY = 2
THURSDAY = 3
FRIDAY = 4
SATURDAY = 5
SUNDAY = 6


# Load environment variables from .env file
load_dotenv()


class TennisCourtChecker:
    def __init__(self):
        # Get Telegram credentials from environment variables
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # Constants
        self.itc_filter_enabled = False
        self.itc_days_to_filter = [MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY]
        self.itc_start_time = datetime.strptime("08:00", "%H:%M")
        self.itc_end_time = datetime.strptime("23:00", "%H:%M")
        self.highbury_filter_enabled = True
        self.highbury_days_to_filter = [SATURDAY, SUNDAY]
        self.highbury_start_time = datetime.strptime("08:00", "%H:%M")
        self.highbury_end_time = datetime.strptime("23:00", "%H:%M")
        self.refresh_period = 15
        self.simplified_notification_text_enabled = True

        if not self.telegram_bot_token or not self.telegram_chat_id:
            raise ValueError("Telegram Bot Token and Chat ID must be set in .env file")

        self.telegram_bot = telegram.Bot(token=self.telegram_bot_token)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)

        self.base_url = "https://better-admin.org.uk/api/activities/venue/islington-tennis-centre/activity/tennis-court-indoor/times"
        self.base_url_highbury = "https://better-admin.org.uk/api/activities/venue/islington-tennis-centre/activity/highbury-tennis/times"

        self.headers = {
            "accept": "application/json",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            "origin": "https://bookings.better.org.uk",
            "priority": "u=1, i",
            "referer": "https://bookings.better.org.uk/location/islington-tennis-centre/tennis-court-indoor/{}/by-time",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }

        # TODO: need to refactor functions such that it takes in different persistent mappings and headers, but re-use same logic entirely
        self.headers_highbury = {
            "accept": "application/json",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            "origin": "https://bookings.better.org.uk",
            "priority": "u=1, i",
            "referer": "https://bookings.better.org.uk/location/islington-tennis-centre/highbury-tennis/{}/by-time",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }

    def is_time_slot_allowed(self, slot):
        try:
            venue = slot.get("name", "")
            date = slot.get("date", "")
            day_dt = datetime.strptime(date, "%Y-%m-%d").weekday()
            time_slot = slot.get("starts_at", {}).get("format_24_hour", "00:00")
            time_slot_dt = datetime.strptime(time_slot, "%H:%M")

            # self.logger.info(f"Checking {venue} for {date}, {day_dt} at {time_slot_dt}")

            if venue == "Highbury Fields Tennis":
                if not self.highbury_filter_enabled:
                    return True
                return day_dt in self.highbury_days_to_filter and self.highbury_start_time <= time_slot_dt < self.highbury_end_time    


            if venue == "Tennis Court - Indoor":
                if not self.itc_filter_enabled:
                    return True
                return day_dt in self.itc_days_to_filter and self.itc_start_time <= time_slot_dt < self.itc_end_time    
        except ValueError:
            return False

    def check_availability(self, date, headers, base_url):
        try:
            headers["referer"] = headers["referer"].format(date)

            response = requests.get(f"{base_url}?date={date}", headers=headers)
            response.raise_for_status()
            data = response.json().get("data", [])
            # self.logger.info(f"Requesting {date}. Response: {data}")
            available_slots = []
            if isinstance(data, list):
                available_slots = [
                    slot
                    for slot in data
                    if slot.get("spaces", 0) > 0
                    and self.is_time_slot_allowed(slot)
                ]
            elif isinstance(data, dict):
                available_slots = [
                    slot
                    for _, slot in data.items()
                    if slot.get("spaces", 0) > 0
                    and self.is_time_slot_allowed(slot)
                ]
            # self.logger.info(f"Slots for  {date}: {available_slots}")
            return available_slots

        except requests.RequestException as e:
            self.logger.error(f"Request error for {date}: {e}")
            return []

    def pretty_print_slots(self, heading, slots):
        sb = []
        sb.append(f"{heading} = [")
        if isinstance(slots, list):
            for slot in slots:
                sb.append(
                    f"{{location: {slot.get('name', '')}, time: {slot.get('starts_at', {}).get('format_24_hour', 'Unknown')}}}, "
                )
        elif isinstance(slots, dict):
            for _, slot in slots.items():
                sb.append(
                    f"{{location: {slot.get('name', '')}, time: {slot.get('starts_at', {}).get('format_24_hour', 'Unknown')}}}, "
                )
        sb.append("]")
        self.logger.info("".join(sb))

    def format_timerange(self, slot):
        return f"{slot.get('starts_at', {}).get('format_24_hour', 'Unknown')}-{slot.get('ends_at', {}).get('format_24_hour', 'Unknown')}"

    def extract_key_from_slot(self, slot):
        return f"{{location: {slot.get('name', '')}, time: {slot.get('starts_at', {}).get('format_24_hour', 'Unknown')}}}"

    async def send_telegram_notification(self, date, slot):
        time_range = self.format_timerange(slot)
        # booking_link = f"https://bookings.better.org.uk/location/islington-tennis-centre/tennis-court-indoor/{date}/by-time/slot/{time_range}"

        message = (
            f"🎾 Available court for \"{slot.get('name')}\"!\n"
            f"Date: {date}\n"
            f"Time: {time_range}\n"
            f"Available Spaces: {slot.get('spaces', 0)}\n"
        )
        if not self.simplified_notification_text_enabled:
            message += (
                f"Price: {slot.get('price', {}).get('formatted_amount', 'N/A')}\n"
                # f"Book Now: {booking_link}"
            )

        # Catch error here as Telegram does some rate limiting which throws an error, and would cause problems
        # with the main loop logic for checking availability deltas
        try:
            await self.telegram_bot.send_message(
                chat_id=self.telegram_chat_id, text=message
            )
        except Exception as e:
            self.logger.error(f"Error sending message for {date}/{time_range}: {e}")
    

    async def get_initial_previous_available_slots_dict(self):
        return {
            datetime.now().strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"): set(),
        }

    async def find_availability(self, headers, previous_available_slots):
        return True

    async def monitor_availability(self):
        previous_available_slots = {}

        while True:
            for days_ahead in range(6):
                check_date = (datetime.now() + timedelta(days=days_ahead)).strftime(
                    "%Y-%m-%d"
                )
                readable_date = (datetime.now() + timedelta(days=days_ahead)).strftime(
                    "%a, %d %b"
                )

                try:
                    loop = asyncio.get_running_loop()
                    available_slots = await loop.run_in_executor(
                        None,
                        self.check_availability,
                        check_date,
                        self.headers,
                        self.base_url,
                    )
                    available_slots.extend(
                        await loop.run_in_executor(
                            None,
                            self.check_availability,
                            check_date,
                            self.headers_highbury,
                            self.base_url_highbury,
                        )
                    )

                    previous_available_slots.setdefault(check_date, set())

                    # Set of available slots (in key form)
                    current_available_slots = {
                        self.extract_key_from_slot(slot) for slot in available_slots
                    }
                    # Set of unavailable slots (in key form)
                    unavailable_slots = (
                        previous_available_slots[check_date] - current_available_slots
                    )
                    # self.logger.info(f"unavailable_slots={unavailable_slots}")
                    # List of slots in its raw dict form
                    new_slots = [
                        slot
                        for slot in available_slots
                        if self.extract_key_from_slot(slot)
                        not in previous_available_slots[check_date]
                    ]
                    # self.logger.info(f"new_slots={new_slots}")

                    # self.logger.info(f"New slots for {check_date}: {new_slots}")
                    self.logger.info(
                        f"prev available slots for {check_date} = {previous_available_slots[check_date]}"
                    )
                    self.pretty_print_slots(
                        f"new available slots for  {check_date}", new_slots
                    )

                    for slot in new_slots:
                        # await self.send_telegram_notification(readable_date, slot)
                        previous_available_slots[check_date].add(
                            self.extract_key_from_slot(slot)
                        )
                    for slot_key in unavailable_slots:
                        previous_available_slots[check_date].remove(slot_key)

                except Exception as e:
                    tb = traceback.format_exc()
                    self.logger.error(
                        f"Error checking availability for {check_date}: {e}\n{tb}"
                    )

            await asyncio.sleep(self.refresh_period)


async def main():
    checker = TennisCourtChecker()
    await checker.monitor_availability()


if __name__ == "__main__":
    asyncio.run(main())
