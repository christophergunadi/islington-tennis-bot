import os
import requests
from datetime import datetime, timedelta
import telegram
import asyncio
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class TennisCourtChecker:
    def __init__(self):
        # Get Telegram credentials from environment variables
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.start_time = datetime.strptime("08:00", "%H:%M")
        self.end_time = datetime.strptime("23:00", "%H:%M")

        if not self.telegram_bot_token or not self.telegram_chat_id:
            raise ValueError("Telegram Bot Token and Chat ID must be set in .env file")

        self.telegram_bot = telegram.Bot(token=self.telegram_bot_token)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

        self.base_url = "https://better-admin.org.uk/api/activities/venue/islington-tennis-centre/activity/tennis-court-indoor/times"

        self.headers = {
            'accept': 'application/json',
            'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'origin': 'https://bookings.better.org.uk',
            'priority': 'u=1, i',
            'referer': 'https://bookings.better.org.uk/location/islington-tennis-centre/tennis-court-indoor/{}/by-time',
            'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A_Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'cross-site',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        }

        self.previous_available_slots = {
            datetime.now().strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d"): set(),
            (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"): set()
        }

    def is_time_slot_allowed(self, time_slot):
        try:
            time_slot_dt = datetime.strptime(time_slot, "%H:%M")
            return self.start_time <= time_slot_dt < self.end_time

        except ValueError:
            return False

    def check_availability(self, date):
        try:
            self.headers['referer'] = self.headers['referer'].format(date)

            response = requests.get(
                f"{self.base_url}?date={date}",
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json().get('data', [])
            # self.logger.info(f"Requesting {date}. Response: {data}")
            available_slots = []
            if isinstance(data, list):
                available_slots = [slot for slot in data if slot.get('spaces', 0) > 0 and self.is_time_slot_allowed(slot.get('starts_at', {}).get('format_24_hour', '00:00'))]
            elif isinstance(data, dict):
                available_slots = [slot for _, slot in data.items() if slot.get('spaces', 0) > 0 and self.is_time_slot_allowed(slot.get('starts_at', {}).get('format_24_hour', '00:00'))]
            self.logger.info(f"Slots for  {date}: {available_slots}")
            return available_slots

        except requests.RequestException as e:
            self.logger.error(f"Request error for {date}: {e}")
            return []

    def format_timerange(self, slot):
        return f"{slot.get('starts_at', {}).get('format_24_hour', 'Unknown')}-{slot.get('ends_at', {}).get('format_24_hour', 'Unknown')}"

    async def send_telegram_notification(self, date, slot):
        time_range = self.format_timerange(slot)
        booking_link = f"https://bookings.better.org.uk/location/islington-tennis-centre/tennis-court-indoor/{date}/by-time/slot/{time_range}"

        message = (
            f"🎾 Tennis Court Available!\n"
            f"Date: {date}\n"
            f"Time: {time_range}\n"
            f"Available Spaces: {slot.get('spaces', 0)}\n"
            f"Price: {slot.get('price', {}).get('formatted_amount', 'N/A')}\n"
            f"Book Now: {booking_link}"
        )

        await self.telegram_bot.send_message(
            chat_id=self.telegram_chat_id,
            text=message
        )

    async def monitor_availability(self):
        while True:
            for days_ahead in range(6):
                check_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

                try:
                    loop = asyncio.get_running_loop()
                    available_slots = await loop.run_in_executor(None, self.check_availability, check_date)
                    current_available_slots = {
                        self.format_timerange(slot)
                        for slot in available_slots
                    }
                    unavailable_slots = self.previous_available_slots[check_date] - current_available_slots
                    new_slots = [
                        slot for slot in available_slots
                        if self.format_timerange(slot)
                        not in self.previous_available_slots[check_date]
                    ]
                    # self.logger.info(f"New slots for {check_date}: {new_slots}")

                    for slot in new_slots:
                        await self.send_telegram_notification(check_date, slot)
                        self.previous_available_slots[check_date].add(
                            self.format_timerange(slot)
                        )
                    for slot in unavailable_slots:
                        self.previous_available_slots[check_date].remove(self.format_timerange(slot))

                except Exception as e:
                    self.logger.error(f"Error checking availability for {check_date}: {e}")

            await asyncio.sleep(10)

async def main():
    checker = TennisCourtChecker()
    await checker.monitor_availability()

if __name__ == "__main__":
    asyncio.run(main())
