from typing import Callable, List

from adplus import Hass


class Mocks:
    def __init__(
        self,
        hass: Hass,
        mock_config: dict,
        mock_callbacks: List[Callable],
        run_mocks: bool = False,
        init_delay: int = 1,
        mock_delay: int = 1,
    ):
        self.hass = hass
        self.config = mock_config
        self.run_mocks = run_mocks
        self.callbacks = mock_callbacks
        self.init_delay = init_delay
        self.mock_delay = mock_delay

        if self.run_mocks:
            self.hass.run_in(self.init_mocks, self.init_delay)

    def init_mocks(self, kwargs):
        self.hass.log("Running Mocks")
        mock_delay = 0
        for mock in self.config:
            self.hass.run_in(
                self.run_mock,
                mock_delay := mock_delay + self.mock_delay,
                mock_config=mock,
            )

    def run_mock(self, kwargs):
        """
        Weird - I can't send the callback in the init_mocks above. Some sort of strange pickling / lock error.
        So instead I'll do the callback loop here.
        """
        mock_config = kwargs["mock_config"]

        self.hass.log(f"\n\n==========\nMOCK: {mock_config}")
        for callback in self.callbacks:
            self.hass.run_in(callback, 0, mock_data=mock_config)
