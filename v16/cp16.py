import asyncio
import logging
import random
from datetime import datetime, timezone
import websockets
from rich.console import Console
from rich.panel import Panel
from rich.logging import RichHandler
from ocpp.v16 import ChargePoint as BaseChargePoint, call
from ocpp.v16.enums import RegistrationStatus

# Setup rich logging
logging.basicConfig(
    level=logging.INFO, handlers=[RichHandler()],
    format="%(message)s"
)
logger = logging.getLogger("cp")
console = Console()

VENDORS = ["The Mobility House", "EVTech", "ChargeFast", "GreenCharge"]
MODELS = ["Optimus", "Eagle", "Falcon", "Hawk"]

class ChargePoint(BaseChargePoint):
    def _print_direction(self, msg: str, direction: str):
        arrow = "[bold green]→[/]" if direction == "cp→csms" else "[bold blue]←[/]"
        console.print(f"{arrow} {msg}")

    async def send_boot_notification(self, model: str, vendor: str):
        self._print_direction(f"Sending BootNotification (model={model}, vendor={vendor})", "cp→csms")
        req = call.BootNotification(
            charge_point_model=model,
            charge_point_vendor=vendor
        )
        resp = await self.call(req)
        if resp.status == RegistrationStatus.accepted:
            self._print_direction("BootNotification accepted", "csms→cp")
            logger.info(f"{self.id} registered with CSMS")

    async def start_charging(self, connector_id: int, id_tag: str):
        self._print_direction(f"Authorizing id_tag={id_tag}", "cp→csms")
        auth = await self.call(call.Authorize(id_tag=id_tag))
        self._print_direction(f"Authorization status: {auth.id_tag_info['status']}", "csms→cp")
        if auth.id_tag_info["status"] != "Accepted":
            logger.error(f"{self.id}: Authorization failed - aborting charge")
            return

        self._print_direction(f"Starting Transaction on connector {connector_id}", "cp→csms")
        txn = await self.call(
            call.StartTransaction(
                connector_id=connector_id,
                id_tag=id_tag,
                meter_start=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )
        tx_id = txn.transaction_id
        self._print_direction(f"Transaction accepted id={tx_id}", "csms→cp")

        # Simulate charging
        for minute in range(1, 11):
            value = minute * 700
            self._print_direction(f"Sending MeterValues {value} Wh", "cp→csms")
            await self.call(
                call.MeterValues(
                    connector_id=connector_id,
                    transaction_id=tx_id,  # Include transaction_id
                    meter_value=[{
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "sampled_value": [{"value": str(value), "unit": "Wh"}]
                    }]
                )
            )
            await asyncio.sleep(2)  # Speeding up the script, change to 60 for accuracy to logic

        self._print_direction(f"Stopping Transaction id={tx_id}", "cp→csms")
        await self.call(
            call.StopTransaction(transaction_id=tx_id, meter_stop=7000, id_tag=id_tag, timestamp=datetime.now(timezone.utc).isoformat())
        )
        self._print_direction("Transaction stopped and session completed", "csms→cp")
        logger.info(f"{self.id}: Charging session completed successfully")

async def run_cp_instance(index: int, connector_id: int, id_tag: str):
    cp_id = f"CP_{index}"
    vendor = random.choice(VENDORS)
    model = random.choice(MODELS)
    uri = f"ws://localhost:9000/{cp_id}"
    console.print(Panel(f"[bold magenta]Connecting {cp_id} to CSMS at {uri}[/]"))
    async with websockets.connect(uri, subprotocols=["ocpp1.6"]) as ws:
        cp = ChargePoint(cp_id, ws)
        await asyncio.gather(
            cp.start(),
            cp.send_boot_notification(model, vendor),
            cp.start_charging(connector_id=connector_id, id_tag=id_tag)
        )

async def main():
    # Prompt user for inputs instead of CLI args
    num_cp = int(input("Enter number of ChargePoints to simulate: "))
    connector = int(input("Enter connector ID for all CPs: "))
    id_tag = input("Enter RFID tag to use for authorization: ")

    tasks = [
        run_cp_instance(i+1, connector, id_tag)
        for i in range(num_cp)
    ]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())