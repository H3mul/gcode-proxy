"""Tests for the handlers module."""

import pytest

from src.gcode_proxy.handlers import (
    GCodeHandler,
    ResponseHandler,
    DefaultGCodeHandler,
    DefaultResponseHandler,
    GCodeHandlerPreResponse,
)


class TestDefaultGCodeHandler:
    """Tests for DefaultGCodeHandler."""

    @pytest.fixture
    def handler(self):
        """Create a DefaultGCodeHandler instance."""
        return DefaultGCodeHandler()

    @pytest.mark.asyncio
    async def test_on_gcode_pre_returns_none(self, handler):
        """Test that on_gcode_pre returns None for default behavior."""
        gcode = "G28 X Y Z"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_gcode_pre(gcode, client_address)
        
        assert result is None

    @pytest.mark.asyncio
    async def test_on_gcode_post_returns_none(self, handler):
        """Test that on_gcode_post returns None."""
        gcode = "G28 X Y Z"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_gcode_post(gcode, client_address)
        
        assert result is None


class TestDefaultResponseHandler:
    """Tests for DefaultResponseHandler."""

    @pytest.fixture
    def handler(self):
        """Create a DefaultResponseHandler instance."""
        return DefaultResponseHandler()

    @pytest.mark.asyncio
    async def test_on_response_does_nothing(self, handler):
        """Test that on_response completes without error."""
        response = "ok"
        gcode = "G28"
        client_address = ("127.0.0.1", 12345)
        
        # Should not raise
        await handler.on_response(response, gcode, client_address)


class TestCustomGCodeHandler:
    """Tests for creating custom GCode handlers by subclassing."""

    @pytest.mark.asyncio
    async def test_custom_handler_can_return_response(self):
        """Test that a custom handler can return GCodeHandlerPreResponse."""
        
        class CustomHandler(GCodeHandler):
            async def on_gcode_pre(
                self, gcode: str, client_address: tuple[str, int]
            ) -> GCodeHandlerPreResponse | None:
                if gcode.strip() == "G28":
                    return GCodeHandlerPreResponse(
                        should_forward=False,
                        fake_response="ok",
                        should_synchronize=False,
                    )
                return None
            
            async def on_gcode_post(
                self, gcode: str, client_address: tuple[str, int]
            ) -> str | None:
                return None
        
        handler = CustomHandler()
        result = await handler.on_gcode_pre("G28", ("127.0.0.1", 12345))
        
        assert result is not None
        assert result.should_forward is False
        assert result.fake_response == "ok"
        assert result.should_synchronize is False

    @pytest.mark.asyncio
    async def test_custom_handler_can_filter_gcode(self):
        """Test that a custom handler can filter certain GCode."""
        
        class FilterHandler(GCodeHandler):
            async def on_gcode_pre(
                self, gcode: str, client_address: tuple[str, int]
            ) -> GCodeHandlerPreResponse | None:
                # Block M112 (emergency stop)
                if "M112" in gcode:
                    return GCodeHandlerPreResponse(
                        should_forward=False,
                        fake_response="error: M112 blocked",
                        should_synchronize=False,
                    )
                return None
            
            async def on_gcode_post(
                self, gcode: str, client_address: tuple[str, int]
            ) -> str | None:
                return None
        
        handler = FilterHandler()
        
        # M112 should be blocked
        result = await handler.on_gcode_pre("M112", ("127.0.0.1", 12345))
        assert result is not None
        assert result.should_forward is False
        
        # Other commands should pass through
        result = await handler.on_gcode_pre("G28", ("127.0.0.1", 12345))
        assert result is None

    @pytest.mark.asyncio
    async def test_custom_handler_can_set_synchronize(self):
        """Test that a custom handler can set synchronize flag."""
        
        class SyncHandler(GCodeHandler):
            async def on_gcode_pre(
                self, gcode: str, client_address: tuple[str, int]
            ) -> GCodeHandlerPreResponse | None:
                if gcode.strip().startswith("M104"):
                    # Require synchronization for temperature commands
                    return GCodeHandlerPreResponse(
                        should_forward=True,
                        fake_response=None,
                        should_synchronize=True,
                    )
                return None
            
            async def on_gcode_post(
                self, gcode: str, client_address: tuple[str, int]
            ) -> str | None:
                return None
        
        handler = SyncHandler()
        result = await handler.on_gcode_pre("M104 S200", ("127.0.0.1", 12345))
        
        assert result is not None
        assert result.should_synchronize is True


class TestCustomResponseHandler:
    """Tests for creating custom response handlers by subclassing."""

    @pytest.mark.asyncio
    async def test_custom_handler_can_track_responses(self):
        """Test that a custom handler can track responses."""
        
        class TrackingResponseHandler(ResponseHandler):
            def __init__(self):
                self.history = []
            
            async def on_response(
                self, response: str, gcode: str, client_address: tuple[str, int]
            ) -> None:
                self.history.append({
                    "response": response,
                    "gcode": gcode,
                    "client": client_address,
                })
        
        handler = TrackingResponseHandler()
        client = ("127.0.0.1", 12345)
        
        await handler.on_response("ok", "G28", client)
        await handler.on_response("ok T:200.0", "M105", client)
        
        assert len(handler.history) == 2
        assert handler.history[0]["gcode"] == "G28"
        assert handler.history[1]["gcode"] == "M105"

    @pytest.mark.asyncio
    async def test_custom_handler_can_log_errors(self):
        """Test that a custom handler can log error responses."""
        
        class ErrorTrackingHandler(ResponseHandler):
            def __init__(self):
                self.errors = []
            
            async def on_response(
                self, response: str, gcode: str, client_address: tuple[str, int]
            ) -> None:
                if response.startswith("error"):
                    self.errors.append({
                        "response": response,
                        "gcode": gcode,
                        "client": client_address,
                    })
        
        handler = ErrorTrackingHandler()
        
        await handler.on_response("ok", "G28", ("127.0.0.1", 12345))
        await handler.on_response("error: something", "M8", ("127.0.0.1", 12345))
        await handler.on_response("ok", "G1 X10", ("127.0.0.1", 12345))
        
        assert len(handler.errors) == 1
        assert handler.errors[0]["gcode"] == "M8"


class TestGCodeHandlerPreResponse:
    """Tests for the GCodeHandlerPreResponse dataclass."""

    def test_create_with_all_fields(self):
        """Test creating a response with all fields."""
        response = GCodeHandlerPreResponse(
            should_forward=True,
            fake_response="ok",
            should_synchronize=True,
        )
        
        assert response.should_forward is True
        assert response.fake_response == "ok"
        assert response.should_synchronize is True

    def test_create_with_none_fake_response(self):
        """Test creating a response with None fake_response."""
        response = GCodeHandlerPreResponse(
            should_forward=True,
            fake_response=None,
            should_synchronize=False,
        )
        
        assert response.fake_response is None

    def test_create_capture_response(self):
        """Test creating a CAPTURE-style response."""
        response = GCodeHandlerPreResponse(
            should_forward=False,
            fake_response="ok",
            should_synchronize=False,
        )
        
        assert response.should_forward is False
        assert response.fake_response is not None
        assert response.should_synchronize is False

    def test_create_forward_response(self):
        """Test creating a FORWARD-style response."""
        response = GCodeHandlerPreResponse(
            should_forward=True,
            fake_response=None,
            should_synchronize=False,
        )
        
        assert response.should_forward is True
        assert response.fake_response is None
        assert response.should_synchronize is False

    def test_create_synchronize_response(self):
        """Test creating a response that requires synchronization."""
        response = GCodeHandlerPreResponse(
            should_forward=True,
            fake_response=None,
            should_synchronize=True,
        )
        
        assert response.should_synchronize is True


class TestHandlerIntegration:
    """Integration tests for handlers working together."""

    @pytest.mark.asyncio
    async def test_gcode_handler_and_response_handler_together(self):
        """Test that GCode and Response handlers work together."""
        
        class TrackingGCodeHandler(GCodeHandler):
            def __init__(self):
                self.commands = []
            
            async def on_gcode_pre(
                self, gcode: str, client_address: tuple[str, int]
            ) -> GCodeHandlerPreResponse | None:
                self.commands.append(gcode)
                return None
            
            async def on_gcode_post(
                self, gcode: str, client_address: tuple[str, int]
            ) -> str | None:
                return None
        
        class TrackingResponseHandler(ResponseHandler):
            def __init__(self):
                self.responses = []
            
            async def on_response(
                self, response: str, gcode: str, client_address: tuple[str, int]
            ) -> None:
                self.responses.append(response)
        
        gcode_handler = TrackingGCodeHandler()
        response_handler = TrackingResponseHandler()
        
        # Simulate processing
        await gcode_handler.on_gcode_pre("G28", ("127.0.0.1", 12345))
        await response_handler.on_response("ok", "G28", ("127.0.0.1", 12345))
        
        await gcode_handler.on_gcode_pre("M104 S200", ("127.0.0.1", 12345))
        await response_handler.on_response("ok", "M104 S200", ("127.0.0.1", 12345))
        
        assert len(gcode_handler.commands) == 2
        assert len(response_handler.responses) == 2
        assert gcode_handler.commands[0] == "G28"
        assert response_handler.responses[0] == "ok"