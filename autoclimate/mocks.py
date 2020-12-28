from .protocol import AutoClimateProto

def init_mocks(self: AutoClimateProto, kwargs):
    if {'mock_config', 'mock_callback'} > set(kwargs):
        self.error(f'Invalid kwargs for init_mocks: {kwargs}')
        return

    if self.test_mode:
        self.log('Running Mocks')
        mock_delay = 0
        for mock in kwargs["mock_config"]:
            self.run_in(
                run_mock, mock_delay := mock_delay + 1, mock_config=mock, 
                mock_callback =kwargs["mock_callback"]
            )

def run_mock(self:AutoClimateProto, kwargs):
    mock_config = kwargs["mock_config"]
    callback = kwargs["mock_callback"]
    self.log(f"\n\n==========\nMOCK: {mock_config}")

    self.run_in(callback, 0, mock_data=mock_config)
