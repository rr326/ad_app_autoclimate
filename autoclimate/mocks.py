from adplus import Hass
from typing import List, Callable


class Mocks(Hass):
    def __init__(
        self,
        *args,
        mock_config: dict,
        test_mode: bool = False,
        mock_callbacks: List[Callable],
        init_delay: int = 1,
        mock_delay: int = 1,
    ):
        super().__init__(*args)

        self.config = mock_config
        self.test_mode = test_mode
        self.callbacks = mock_callbacks
        self.init_delay = init_delay
        self.mock_delay = mock_delay

        if self.test_mode:
            self.run_in(self.init_mocks, self.init_delay)

    def init_mocks(self, kwargs):
        self.log("Running Mocks")
        mock_delay = 0
        for mock in self.config:
            for callback in self.callbacks:
                self.run_in(
                    self.run_mock,
                    mock_delay := mock_delay + self.mock_delay,
                    mock_config=mock,
                    mock_callback=callback,
                    )

    def run_mock(self, kwargs):
        mock_config = kwargs["mock_config"]
        callback = kwargs["mock_callback"]
        self.log(f"\n\n==========\nMOCK: {mock_config}")

        self.run_in(callback, 0, mock_data=mock_config)
