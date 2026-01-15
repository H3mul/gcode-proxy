# GCode Triggers

GCode Proxy supports custom triggers that allow you to execute external commands in response to GCode patterns. This enables integration with external systems like Home Assistant, shell scripts, or other automation tools.

## Overview

Triggers are defined in the configuration file and consist of:
- **id**: A unique identifier for the trigger (used in logging)
- **trigger**: The matching criteria (currently supports GCode pattern matching)
- **command**: The external command to execute when a match is found

## Configuration

Triggers are defined under the `custom-triggers` section in the configuration file:

```yaml
server:
  port: 8080
  address: 0.0.0.0

device:
  usb-id: "303a:4001"
  baud-rate: 115200

custom-triggers:
  - id: air-assist-on
    trigger:
      type: gcode
      match: M8
    command: "./scripts/air_assist_on.py"
  
  - id: air-assist-off
    trigger:
      type: gcode
      match: M9
    command: "./scripts/air_assist_off.py"
  
  - id: spindle-speed
    trigger:
      type: gcode
      match: "S[0-9]+"
    command: "echo 'Spindle speed change detected'"
```

## Trigger Types

### GCode Triggers

GCode triggers match incoming GCode commands using regular expressions.

**Schema:**
```yaml
trigger:
  type: gcode
  match: <regex_pattern>
```

**Examples:**

```yaml
# Exact match
- trigger:
    type: gcode
    match: M8

# Case-sensitive alternatives
- trigger:
    type: gcode
    match: "M[89]"

# Complex patterns
- trigger:
    type: gcode
    match: "G1.*X[0-9]+"
```

## Pattern Matching

The `match` field uses standard Python regular expressions. Some common patterns:

| Pattern | Matches |
|---------|---------|
| `M8` | Exactly "M8" |
| `M[89]` | "M8" or "M9" |
| `G1.*X` | "G1" followed by any characters, then "X" |
| `S[0-9]+` | "S" followed by one or more digits |
| `G0[01]` | "G00" or "G01" |
| `.*Z.*` | Any command containing "Z" |

The matching is case-sensitive and matches against the stripped GCode command.

## Command Execution

When a GCode pattern matches:

1. The matched GCode is immediately passed through to the device (triggers don't block)
2. A background task is spawned to execute the command asynchronously
3. The command executes in a shell environment
4. Execution is logged at INFO level
5. If the command fails (non-zero exit code), it's logged at ERROR level

### Example Commands

**Python script:**
```yaml
command: "python3 /path/to/script.py --arg value"
```

**Shell command:**
```yaml
command: "echo 'GCode received' >> /tmp/log.txt"
```

**Home Assistant service call:**
```yaml
command: "curl -X POST http://homeassistant.local:8123/api/services/switch/turn_on -H 'Authorization: Bearer TOKEN' -H 'Content-Type: application/json' -d '{\"entity_id\": \"switch.air_assist\"}'"
```

**Complex bash script:**
```yaml
command: "bash -c 'if [ -f /tmp/flag ]; then echo done; else echo pending; fi'"
```

## Logging

Triggers produce the following log messages:

**When a trigger matches and starts execution:**
```
INFO - Executing trigger 'air-assist-on': ./scripts/air_assist_on.py
```

**When a command succeeds:**
```
INFO - Trigger 'air-assist-on' executed successfully (exit code: 0)
```

**When a command fails:**
```
ERROR - Trigger 'air-assist-on' failed with exit code 1: Command output error message
```

## Async and Non-Blocking

All trigger execution is **asynchronous and non-blocking**:

- GCode patterns are matched synchronously in the `on_gcode_received` handler
- External commands are spawned in background tasks
- Device communication is never blocked by trigger execution
- Multiple triggers can execute concurrently if multiple GCodes match
- The server gracefully waits for all pending trigger tasks during shutdown

## Error Handling

If a trigger is misconfigured:
- The error is logged at startup
- The server exits with an error code
- The configuration file should be corrected and the server restarted

If a command fails during execution:
- The failure is logged at ERROR level
- Execution continues normally
- No retry is attempted

## Configuration Examples

### Basic Example

```yaml
custom-triggers:
  - id: start-logging
    trigger:
      type: gcode
      match: "^G28"
    command: "touch /tmp/job_started.log"
```

### Multiple Triggers for Same Pattern

Multiple triggers can match the same GCode - all matching triggers will execute:

```yaml
custom-triggers:
  - id: log-air-assist
    trigger:
      type: gcode
      match: M8
    command: "echo 'Air assist enabled' >> /var/log/gcode.log"
  
  - id: home-assistant-air-assist
    trigger:
      type: gcode
      match: M8
    command: "curl -s http://homeassistant/api/services/switch/turn_on -d entity_id=switch.air_assist"
```

### Complex Pattern Matching

```yaml
custom-triggers:
  - id: detect-rapid-moves
    trigger:
      type: gcode
      match: "G0.*"  # G0 rapid positioning
    command: "./scripts/rapid_move.sh"
  
  - id: detect-line-moves
    trigger:
      type: gcode
      match: "G1.*"  # G1 linear interpolation
    command: "./scripts/linear_move.sh"
  
  - id: spindle-control
    trigger:
      type: gcode
      match: "M3|M4|M5"  # Spindle on/off
    command: "./scripts/spindle_control.sh"
```

### Integration with External Tools

```yaml
custom-triggers:
  - id: notify-on-error
    trigger:
      type: gcode
      match: "M108"  # Filament change request
    command: 'notify-send "Filament change requested"'
  
  - id: update-web-dashboard
    trigger:
      type: gcode
      match: "G0"
    command: "curl -X POST http://dashboard.local/update -d @/tmp/machine_state.json"
```

## Limitations and Future Extensions

**Current limitations:**
- Only GCode-based triggers are supported
- Commands execute in the system shell
- No parameter passing from GCode to commands (future enhancement)
- No response modification based on trigger results

**Future trigger types could include:**
- Response-based triggers (matching device responses)
- Timer-based triggers
- State-based triggers
- Multi-pattern triggers

## Testing Triggers

To test triggers without actual hardware:

```bash
gcode-proxy-server --dry-run --config /path/to/config.yaml
```

In dry-run mode:
- The server listens for TCP connections
- GCode commands are processed normally
- Triggers match and execute commands
- No actual device communication occurs

## Troubleshooting

**Trigger not executing:**
- Check that the GCode pattern matches (case-sensitive)
- Verify the command path is correct
- Check logs for pattern matching errors
- Ensure the command has execute permissions

**Command fails silently:**
- Check ERROR logs for the actual failure message
- Test the command in the shell directly
- Ensure the command is in PATH or use absolute paths

**Server startup fails:**
- Check for invalid regex patterns in trigger definitions
- Verify all required fields (id, trigger, command) are present
- Check for YAML syntax errors

## Performance Considerations

- Pattern matching is fast (compiled regex)
- Background task spawning is lightweight
- Multiple concurrent triggers are supported
- No blocking occurs on device communication
- Resource usage scales with number of commands executing

For high-frequency triggers (e.g., matching every move command), consider using shell scripts that are already compiled or JIT-compiled languages for best performance.