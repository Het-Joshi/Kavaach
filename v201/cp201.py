import asyncio
import logging
import websockets
import ssl
from datetime import datetime, timezone
from rich.console import Console
from rich.panel import Panel
from rich.logging import RichHandler
from ocpp.routing import on
from ocpp.v201 import ChargePoint as cp, call, call_result
from ocpp.v201.enums import (
    RegistrationStatusEnumType, FirmwareStatusEnumType, AuthorizationStatusEnumType
)

# Setup rich logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[RichHandler()],
    format="%(message)s"
)
logger = logging.getLogger("cp201")
console = Console()

# Create SSL context for client
# Note: Load the CSMS's certificate (csmscert.pem) to trust the server.
# Ensure csmscert.pem includes 'localhost' in its Subject Alternative Name (SAN).
# Generate with: openssl req -x509 -newkey rsa:4096 -keyout csmskey.pem -out csmscert.pem -days 365 -nodes -config san.cnf
ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.load_verify_locations('csmscert.pem')  # Trust CSMS's certificate
# Optional: Load CP's own certificate and key if client authentication is required
# ssl_context.load_cert_chain('cert.pem', 'key.pem')

class ChargePoint(cp):
    def _print_direction(self, msg: str, direction: str):
        arrow = "[bold green]→[/]" if direction == "cp→csms" else "[bold blue]←[/]"
        console.print(f"{arrow} {msg}")

    async def send_boot_notification(self):
        self._print_direction("Sending BootNotification (model=Wallbox XYZ, vendor=anewone)", "cp→csms")
        request = call.BootNotification(
            charging_station={"model": "Wallbox XYZ", "vendor_name": "anewone"},
            reason="PowerUp"
        )
        try:
            response = await self.call(request)
        except Exception as e:
            logger.error(f"BootNotification failed: {e}")
            return  # Exit if there's an error
        
        if response.status == RegistrationStatusEnumType.accepted:
            self._print_direction("BootNotification accepted", "csms→cp")
            logger.info("Connected to CSMS")

    async def plug_and_charge(self):
        """ISO 15118 Plug & Charge flow."""
        self._print_direction("Authorizing via Plug & Charge", "cp→csms")
        try:
            auth = await self.call(
                call.Authorize(
                    id_token={
                        "type": "eMAID",
                        "idToken": "-----BEGIN CERT...VALID_CERT..."
                    }
                )
            )
        except Exception as e:
            logger.error(f"Authorization failed: {e}")
            return  # Exit on error

        if not auth or auth.id_token_info["status"] != AuthorizationStatusEnumType.accepted:
            logger.error("Plug & Charge failed")
            return
        
        # Add transaction info and sequence counter
        transaction_info = {
            "transaction_id": "TX12345",
            "charging_state": "Charging",
            "time_spent_charging": 0,
        }
        seq_no = 0  # Increment for each event

        # Started event
        seq_no += 1
        self._print_direction("TransactionEvent: Started", "cp→csms")
        await self.call(
            call.TransactionEvent(
                event_type="Started",
                timestamp=datetime.now(timezone.utc).isoformat(),
                trigger_reason="Authorized",
                seq_no=seq_no,
                transaction_info=transaction_info,
                meter_value=[{
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sampled_value": [{
                        "value": 0,
                        "unitOfMeasure": {
                            "unit": "Wh",
                            "multiplier": 0
                        }
                    }]
                }]
            )
        )

        # Updated events
        for minute in range(1, 11):
            seq_no += 1
            value = minute * 700
            self._print_direction(f"TransactionEvent: Updated ({value} Wh)", "cp→csms")
            await self.call(
                call.TransactionEvent(
                    event_type="Updated",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    trigger_reason="MeterValuePeriodic",
                    seq_no=seq_no,
                    transaction_info=transaction_info,
                    meter_value=[{
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "sampled_value": [{
                            "value": value,
                            "unitOfMeasure": {
                                "unit": "Wh",
                                "multiplier": 0
                            }
                        }]
                    }]
                )
            )
            await asyncio.sleep(1)  # Reduce to 1 sec for testing

        # Ended event
        seq_no += 1
        self._print_direction("TransactionEvent: Ended", "cp→csms")
        await self.call(
            call.TransactionEvent(
                event_type="Ended",
                timestamp=datetime.now(timezone.utc).isoformat(),
                trigger_reason="EVDeparted",
                seq_no=seq_no,
                transaction_info=transaction_info,
                meter_value=[{
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sampled_value": [{
                        "value": 7000,
                        "unitOfMeasure": {
                            "unit": "Wh",
                            "multiplier": 0
                        }
                    }]
                }]
            )
        )
        logger.info("Charging session completed")

    @on('UpdateFirmware')
    async def on_update_firmware(self, firmware_url, **kwargs):
        self._print_direction(f"Received UpdateFirmware request: {firmware_url}", "cp→csms")
        asyncio.create_task(self.handle_firmware_update(firmware_url))
        return call_result.UpdateFirmware(status='Accepted')

    async def handle_firmware_update(self, firmware_url):
        self._print_direction(f"Starting firmware update from {firmware_url}", "cp→csms")
        await self.call(call.FirmwareStatusNotification(status='Downloading'))
        await asyncio.sleep(5)  # Simulate download
        await self.call(call.FirmwareStatusNotification(status='Installing'))
        await asyncio.sleep(5)  # Simulate installation
        await self.call(call.FirmwareStatusNotification(status='Installed'))
        self._print_direction("Firmware update completed", "cp→csms")

async def main():
    uri = "wss://localhost:9000/CP_1"
    console.print(Panel(f"[bold magenta]Connecting to CSMS at {uri}[/]"))
    try:
        async with websockets.connect(
            uri, subprotocols=["ocpp2.0.1"], ssl=ssl_context
        ) as ws:
            cp = ChargePoint("CP_1", ws)
            await asyncio.gather(
                cp.start(),
                cp.send_boot_notification(),
                cp.plug_and_charge()
            )
    except ssl.SSLCertVerificationError as e:
        logger.error(f"SSL certificate verification failed: {e}")
    except Exception as e:
        logger.error(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())