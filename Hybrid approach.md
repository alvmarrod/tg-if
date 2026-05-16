**Hybrid approach:**
1. **Phase 1 - Foundation:**
   - Domain data structures
   - Config loading
   - Basic logging setup
   
2. **Phase 2 - Vertical Slice:**
   - Simple SessionManager (one bot)
   - Receive one message → publish to broker
   - Consume response → send to Telegram
   
3. **Phase 3 - Expand:**
   - Full rules engine
   - Multiple bots
   - All event types
   - Health monitoring

