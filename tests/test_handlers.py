"""Tests for the handlers module."""

import pytest

from gcode_proxy.handlers import (
    GCodeHandler,
    ResponseHandler,
    DefaultGCodeHandler,
    DefaultResponseHandler,
    CallbackGCodeHandler,
    CallbackResponseHandler,
)


class TestDefaultGCodeHandler:
    """Tests for DefaultGCodeHandler."""

    @pytest.fixture
    def handler(self):
        """Create a DefaultGCodeHandler instance."""
        return DefaultGCodeHandler()

    @pytest.mark.asyncio
    async def test_on_gcode_received_passes_through(self, handler):
        """Test that on_gcode_received passes through the gcode unchanged."""
        gcode = "G28 X Y Z"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_gcode_received(gcode, client_address)
        
        assert result == gcode

    @pytest.mark.asyncio
    async def test_on_gcode_sent_does_nothing(self, handler):
        """Test that on_gcode_sent completes without error."""
        gcode = "G28 X Y Z"
        client_address = ("127.0.0.1", 12345)
        
        # Should not raise
        await handler.on_gcode_sent(gcode, client_address)


class TestDefaultResponseHandler:
    """Tests for DefaultResponseHandler."""

    @pytest.fixture
    def handler(self):
        """Create a DefaultResponseHandler instance."""
        return DefaultResponseHandler()

    @pytest.mark.asyncio
    async def test_on_response_received_passes_through(self, handler):
        """Test that on_response_received passes through the response unchanged."""
        response = "ok"
        original_gcode = "G28"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_response_received(response, original_gcode, client_address)
        
        assert result == response

    @pytest.mark.asyncio
    async def test_on_response_sent_does_nothing(self, handler):
        """Test that on_response_sent completes without error."""
        response = "ok"
        client_address = ("127.0.0.1", 12345)
        
        # Should not raise
        await handler.on_response_sent(response, client_address)


class TestCallbackGCodeHandler:
    """Tests for CallbackGCodeHandler."""

    @pytest.mark.asyncio
    async def test_with_no_callbacks(self):
        """Test handler works with no callbacks provided."""
        handler = CallbackGCodeHandler()
        gcode = "G28"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_gcode_received(gcode, client_address)
        assert result == gcode
        
        # Should not raise
        await handler.on_gcode_sent(gcode, client_address)

    @pytest.mark.asyncio
    async def test_on_received_callback_is_called(self):
        """Test that on_received callback is invoked."""
        received_data = []
        
        async def on_received(gcode: str, client_address: tuple[str, int]) -> str:
            received_data.append((gcode, client_address))
            return f"modified_{gcode}"
        
        handler = CallbackGCodeHandler(on_received=on_received)
        gcode = "G28"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_gcode_received(gcode, client_address)
        
        assert result == "modified_G28"
        assert received_data == [(gcode, client_address)]

    @pytest.mark.asyncio
    async def test_on_sent_callback_is_called(self):
        """Test that on_sent callback is invoked."""
        sent_data = []
        
        async def on_sent(gcode: str, client_address: tuple[str, int]) -> None:
            sent_data.append((gcode, client_address))
        
        handler = CallbackGCodeHandler(on_sent=on_sent)
        gcode = "G28"
        client_address = ("127.0.0.1", 12345)
        
        await handler.on_gcode_sent(gcode, client_address)
        
        assert sent_data == [(gcode, client_address)]


class TestCallbackResponseHandler:
    """Tests for CallbackResponseHandler."""

    @pytest.mark.asyncio
    async def test_with_no_callbacks(self):
        """Test handler works with no callbacks provided."""
        handler = CallbackResponseHandler()
        response = "ok"
        original_gcode = "G28"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_response_received(response, original_gcode, client_address)
        assert result == response
        
        # Should not raise
        await handler.on_response_sent(response, client_address)

    @pytest.mark.asyncio
    async def test_on_received_callback_is_called(self):
        """Test that on_received callback is invoked."""
        received_data = []
        
        async def on_received(
            response: str, original_gcode: str, client_address: tuple[str, int]
        ) -> str:
            received_data.append((response, original_gcode, client_address))
            return f"modified_{response}"
        
        handler = CallbackResponseHandler(on_received=on_received)
        response = "ok"
        original_gcode = "G28"
        client_address = ("127.0.0.1", 12345)
        
        result = await handler.on_response_received(response, original_gcode, client_address)
        
        assert result == "modified_ok"
        assert received_data == [(response, original_gcode, client_address)]

    @pytest.mark.asyncio
    async def test_on_sent_callback_is_called(self):
        """Test that on_sent callback is invoked."""
        sent_data = []
        
        async def on_sent(response: str, client_address: tuple[str, int]) -> None:
            sent_data.append((response, client_address))
        
        handler = CallbackResponseHandler(on_sent=on_sent)
        response = "ok"
        client_address = ("127.0.0.1", 12345)
        
        await handler.on_response_sent(response, client_address)
        
        assert sent_data == [(response, client_address)]


class TestCustomGCodeHandler:
    """Tests for creating custom GCode handlers by subclassing."""

    @pytest.mark.asyncio
    async def test_custom_handler_can_modify_gcode(self):
        """Test that a custom handler can modify gcode commands."""
        
        class UppercaseHandler(GCodeHandler):
            async def on_gcode_received(
                self, gcode: str, client_address: tuple[str, int]
            ) -> str:
                return gcode.upper()
            
            async def on_gcode_sent(
                self, gcode: str, client_address: tuple[str, int]
            ) -> None:
                pass
        
        handler = UppercaseHandler()
        result = await handler.on_gcode_received("g28 x y z", ("127.0.0.1", 12345))
        
        assert result == "G28 X Y Z"

    @pytest.mark.asyncio
    async def test_custom_handler_can_filter_gcode(self):
        """Test that a custom handler can filter gcode commands."""
        
        class FilterHandler(GCodeHandler):
            async def on_gcode_received(
                self, gcode: str, client_address: tuple[str, int]
            ) -> str:
                # Strip comments
                if ";" in gcode:
                    return gcode.split(";")[0].strip()
                return gcode
            
            async def on_gcode_sent(
                self, gcode: str, client_address: tuple[str, int]
            ) -> None:
                pass
        
        handler = FilterHandler()
        result = await handler.on_gcode_received("G28 ; home all axes", ("127.0.0.1", 12345))
        
        assert result == "G28"


class TestCustomResponseHandler:
    """Tests for creating custom response handlers by subclassing."""

    @pytest.mark.asyncio
    async def test_custom_handler_can_modify_response(self):
        """Test that a custom handler can modify responses."""
        
        class AnnotatedResponseHandler(ResponseHandler):
            async def on_response_received(
                self, response: str, original_gcode: str, client_address: tuple[str, int]
            ) -> str:
                return f"[{original_gcode}] {response}"
            
            async def on_response_sent(
                self, response: str, client_address: tuple[str, int]
            ) -> None:
                pass
        
        handler = AnnotatedResponseHandler()
        result = await handler.on_response_received("ok", "G28", ("127.0.0.1", 12345))
        
        assert result == "[G28] ok"

    @pytest.mark.asyncio
    async def test_custom_handler_can_track_responses(self):
        """Test that a custom handler can track responses for logging."""
        
        class TrackingResponseHandler(ResponseHandler):
            def __init__(self):
                self.history = []
            
            async def on_response_received(
                self, response: str, original_gcode: str, client_address: tuple[str, int]
            ) -> str:
                self.history.append({
                    "response": response,
                    "gcode": original_gcode,
                    "client": client_address,
                })
                return response
            
            async def on_response_sent(
                self, response: str, client_address: tuple[str, int]
            ) -> None:
                pass
        
        handler = TrackingResponseHandler()
        client = ("127.0.0.1", 12345)
        
        await handler.on_response_received("ok", "G28", client)
        await handler.on_response_received("ok T:200.0", "M105", client)
        
        assert len(handler.history) == 2
        assert handler.history[0]["gcode"] == "G28"
        assert handler.history[1]["gcode"] == "M105"