# LLD

> **Note:** This document reflects early design. Current architecture is documented in `doc/architecture_overview.md` and subsystem docs (`doc/subsystems/*.md`). Media retrieval design: `doc/media_retrieval.md`.

## **Data Structures**

| Domain | Type | Description |
| ------ | ---- | ----------- |
| **Domain Layer** | | |
| BotRoutingConfig | Data Structure | Bot identifier and associated routing rules |
| RoutingRule | Data Structure | Single routing rule with condition and target topic |
| RoutingCondition | Data Structure | Conditions to match against events for routing |
| TelegramEvent | Data Structure | Base Telegram event (abstract) |
| MessageEvent | Data Structure | Message-specific event (text, media messages) |
| CommandEvent | Data Structure | Command event (/start, /help, etc.) |
| CallbackQueryEvent | Data Structure | Inline button callback event |
| RoutingContext | Data Structure | Extracted metadata for routing decisions (chat_type, has_media, etc.) |
| OutgoingMessage | Data Structure | Abstract message to send (text content, buttons concept) |
| EventType | Enum | Event type enumeration (message, command, callback_query) |
| ChatType | Enum | Chat type enumeration (private, group, supergroup, channel) |
| **Infrastructure Layer** | | |
| AppConfig | Data Structure | Overall application configuration |
| BrokerConfig | Data Structure | RabbitMQ connection settings |
| LogConfig | Data Structure | Logging configuration |
| TelegramBotCredentials | Data Structure | Telegram API credentials (api_id, api_hash, session_file) |
| TelegramUpdate | Data Structure | Adapter/wrapper for raw Pyrofork updates |
| SessionInfo | Data Structure | Session status and metadata (connected/disconnected, uptime) |
| TelegramResponseFormat | Data Structure | Telegram-specific formatting (parse_mode, reply_markup JSON) |
| IncomingEnvelope | Data Structure | Complete message envelope for incoming events (with routing_context) |
| OutgoingEnvelope | Data Structure | Complete message envelope for outgoing responses |
| PublishResult | Data Structure | Result of publish operation to broker |
| **App Layer** | | |
| ReceiverState | Data Structure | Runtime state of receiver service (active sessions, health status) |
| DispatchResult | Data Structure | Result of event dispatching operation (success, target topic, errors) |
| RoutingDecision | Data Structure | Matched routing rule and determined target topic |

---

## **Services/Classes**

| Domain | Type | Description |
| ------ | ---- | ----------- |
| **Infrastructure Layer** | | |
| ConfigLoader | Class | Loads and parses YAML configuration files (bots.yaml, etc.) |
| SessionManager | Class | Manages Pyrofork sessions lifecycle: load from disk, login/authenticate, keep alive, reconnection with backoff, error handling (flood waits, API errors), state persistence, provide session access via `get_session(bot_id)`, health status reporting, graceful shutdown |
| TelegramClient | Class | Wrapper around single Pyrofork client instance for one bot |
| TelegramEventHandler | Class | Receives Pyrofork updates and initiates processing pipeline |
| EventAdapter | Class | Converts Pyrofork updates to domain TelegramEvent models |
| MessageFormatter | Class | Converts domain OutgoingMessage to Telegram API format (parse_mode, reply_markup) |
| StreamConnection | Class | RabbitMQ Streams connection manager |
| Publisher | Class | Publishes messages to RabbitMQ streams |
| Consumer | Class | Consumes messages from RabbitMQ streams (generic broker consumption) |
| HealthMonitor | Class | Monitors session and broker health status, aggregates health data |
| **App Layer** | | |
| ReceiverService | Class | Main service orchestrator: initializes components, coordinates startup/shutdown, manages service lifecycle |
| EventDispatcher | Class | Orchestrates incoming event flow: calls MetadataExtractor → RulesEngine → EnvelopeBuilder → Publisher |
| RulesEngine | Class | Pure rule matching logic: evaluates RoutingCondition against TelegramEvent/RoutingContext |
| MetadataExtractor | Class | Extracts RoutingContext metadata from TelegramEvent |
| EnvelopeBuilder | Class | Constructs IncomingEnvelope and OutgoingEnvelope structures |
| ResponseConsumer | Class | Consumes OutgoingEnvelope messages from broker (outgoing.responses stream) |
| ResponseSender | Class | Sends responses to Telegram: resolves bot session, formats message, executes Telegram API call |
