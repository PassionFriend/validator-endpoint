import os
import json
from typing import List
from rich.console import Console
import typer

from btvep.types import RateLimit

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config.json")
CONFIG_PATH = os.path.abspath(CONFIG_PATH)

from pydantic import BaseModel


class Config(BaseModel):
    hotkey_mnemonic: str | None = None
    rate_limiting_enabled = False
    redis_url = "redis://localhost"
    global_rate_limits: List[RateLimit] = []

    def to_json(self):
        return json.dumps(self, default=lambda o: o.dict(), sort_keys=False, indent=4)

    def save(self):
        #  save to a json file
        with open(CONFIG_PATH, "w") as jsonfile:
            jsonfile.write(self.to_json())
        return self

    def load(self):
        # load from a json file and handle error silently
        try:
            with open(CONFIG_PATH, "r") as jsonfile:
                json_data = json.load(jsonfile)
                self.__dict__.update(json_data)
            return self
        except FileNotFoundError as e:
            return self
        except json.JSONDecodeError as e:
            err_console = Console(stderr=True)
            err_console.print(
                f"[bold red]Error:[/bold red] {CONFIG_PATH} is not a valid json file. Please fix it or delete it and try again."
            )
            raise typer.Exit(1)

    # Print format
    def __str__(self):
        # use __dict__
        return self.to_json()
