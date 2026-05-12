"""
utils/notifications.py
────────────────────
Strategy execution notification system for Teams webhook integration.

Sends execution summaries to Teams channel with strategy details.
"""

import json
import time
import requests
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class NotificationConfig:
    """Configuration for notification system."""
    webhook_url: str
    enabled: bool = True
    timeout: int = 10
    retry_attempts: int = 3


class NotificationManager:
    """
    Manages strategy execution notifications via Teams webhook.
    
    Features:
    - Strategy execution summaries
    - Entry/exit notifications
    - Error notifications
    - Separate notifications per strategy
    """
    
    def __init__(self, config: NotificationConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'TradingFramework/1.0'
        })
    
    def send_strategy_summary(self, 
                          strategy_name: str,
                          execution_time: datetime,
                          signal: Optional[str] = None,
                          position_size: Optional[int] = None,
                          entry_price: Optional[float] = None,
                          exit_price: Optional[float] = None,
                          pnl: Optional[float] = None,
                          bars_held: Optional[int] = None,
                          profitable_closes: Optional[int] = None,
                          error: Optional[str] = None,
                          indicators: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send strategy execution summary to Teams.
        
        Args:
            strategy_name: Name of the strategy
            execution_time: When the strategy ran
            signal: Signal type (ENTRY_LONG, EXIT_LONG, etc.)
            position_size: Number of contracts
            entry_price: Entry price
            exit_price: Exit price (if applicable)
            pnl: Profit/loss (if applicable)
            bars_held: Number of bars held
            profitable_closes: Number of profitable closes
            error: Error message (if any)
            indicators: Strategy indicators/metrics
            
        Returns:
            True if notification sent successfully
        """
        if not self.config.enabled:
            return True
        
        # Build message content
        title = f"📊 {strategy_name} Strategy Execution"
        
        if error:
            color = "FF0000"  # Red for errors
            status = "❌ ERROR"
            description = f"Strategy execution failed: {error}"
        elif signal and signal.startswith("ENTRY"):
            color = "00FF00"  # Green for entries
            status = "📈 ENTRY"
            description = f"Signal: {signal}\nPosition: {position_size} contracts\nEntry: {entry_price}"
        elif signal and signal.startswith("EXIT"):
            color = "FFA500"  # Orange for exits
            status = "📉 EXIT"
            pnl_str = f"P&L: ${pnl:,.2f}" if pnl is not None else "P&L: N/A"
            description = f"Signal: {signal}\n{pnl_str}\nExit: {exit_price}\nBars held: {bars_held}"
        else:
            color = "0080FF"  # Blue for no action
            status = "ℹ️ INFO"
            description = f"No action taken\nBars held: {bars_held}" if bars_held else "No action taken"
        
        # Add detailed strategy summary if provided
        if indicators:
            # Format like the log output
            summary_lines = []
            
            # Current position
            if 'current_pos' in indicators:
                summary_lines.append(f"Current position: {indicators['current_pos']}")
            
            # Position state
            if 'position_state' in indicators:
                pos_state = indicators['position_state']
                summary_lines.append(f"position_state: {pos_state}")
            
            # Signal details
            if signal and signal != "NONE":
                summary_lines.append(f"Signal: {signal}  reason={indicators.get('reason', 'No reason')}")
            else:
                summary_lines.append(f"Signal: NONE  reason={indicators.get('reason', 'No actionable signal')}")
            
            # Additional indicators
            other_indicators = {k: v for k, v in indicators.items() 
                             if k not in ['current_pos', 'position_state', 'reason', 'close', 'date']}
            if other_indicators:
                summary_lines.append("**Indicators:**")
                for key, value in other_indicators.items():
                    if value is not None:
                        summary_lines.append(f"  {key}: {value}")
            
            description = "\n".join(summary_lines)
        
        # Create Teams message
        message = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "summary": f"{strategy_name} - {status}",
            "sections": [{
                "activityTitle": title,
                "activitySubtitle": f"Executed: {execution_time.strftime('%Y-%m-%d %H:%M:%S')}",
                "facts": [{
                    "name": "Status",
                    "value": status
                }, {
                    "name": "Strategy",
                    "value": strategy_name
                }, {
                    "name": "Time",
                    "value": execution_time.strftime('%Y-%m-%d %H:%M:%S')
                }],
                "text": description
            }],
            "potentialAction": [{
                "@type": "OpenUri",
                "name": "View Logs",
                "targets": [{
                    "os": "default",
                    "uri": "https://github.com/cemcoa-tech/trading-system-architecture"
                }]
            }]
        }
        
        return self._send_webhook(message, f"Strategy summary for {strategy_name}")
    
    def send_system_notification(self, 
                             message: str,
                             level: str = "INFO",
                             timestamp: Optional[datetime] = None) -> bool:
        """
        Send system-level notification.
        
        Args:
            message: Notification message
            level: INFO, WARNING, ERROR
            timestamp: When the event occurred
            
        Returns:
            True if notification sent successfully
        """
        if not self.config.enabled:
            return True
        
        colors = {
            "INFO": "0080FF",    # Blue
            "WARNING": "FFA500",  # Orange
            "ERROR": "FF0000"     # Red
        }
        
        icons = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "❌"
        }
        
        title = f"{icons.get(level, 'ℹ️')} Trading Framework {level}"
        color = colors.get(level, "0080FF")
        timestamp = timestamp or datetime.now()
        
        teams_message = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "summary": f"Trading Framework - {level}",
            "sections": [{
                "activityTitle": title,
                "activitySubtitle": timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                "text": message
            }]
        }
        
        return self._send_webhook(teams_message, "System notification")
    
    def _send_webhook(self, message: Dict[str, Any], description: str) -> bool:
        """
        Send message to Teams webhook with retry logic.
        
        Args:
            message: Teams message card
            description: Description for logging
            
        Returns:
            True if sent successfully
        """
        for attempt in range(self.config.retry_attempts):
            try:
                response = self.session.post(
                    self.config.webhook_url,
                    json=message,
                    timeout=self.config.timeout
                )
                
                if response.status_code in [200, 202]:  # 202 Accepted is also success
                    return True
                else:
                    print(f"Notification failed (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < self.config.retry_attempts - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        
            except requests.exceptions.RequestException as e:
                print(f"Notification error (attempt {attempt + 1}): {e}")
                if attempt < self.config.retry_attempts - 1:
                    time.sleep(2 ** attempt)
        
        print(f"Failed to send notification after {self.config.retry_attempts} attempts: {description}")
        return False


# Global notification manager instance
_notification_manager: Optional[NotificationManager] = None
_startup_notification_sent = False

# Deduplication cache to prevent duplicate notifications
_notification_cache: Dict[str, float] = {}
_DEDUPLICATION_WINDOW = 60  # seconds


def init_notifications(webhook_url: str, enabled: bool = True) -> None:
    """
    Initialize the global notification manager.
    
    Args:
        webhook_url: Teams webhook URL
        enabled: Whether notifications are enabled
    """
    global _notification_manager, _startup_notification_sent, _notification_cache
    _notification_manager = NotificationManager(
        NotificationConfig(webhook_url=webhook_url, enabled=enabled)
    )
    _startup_notification_sent = False  # Reset flag on initialization
    _notification_cache.clear()  # Clear deduplication cache


def notify_strategy_execution(strategy_name: str,
                        execution_time: datetime,
                        signal: Optional[str] = None,
                        position_size: Optional[int] = None,
                        entry_price: Optional[float] = None,
                        exit_price: Optional[float] = None,
                        pnl: Optional[float] = None,
                        bars_held: Optional[int] = None,
                        profitable_closes: Optional[int] = None,
                        error: Optional[str] = None,
                        indicators: Optional[Dict[str, Any]] = None) -> bool:
    """
    Send strategy execution notification.
    
    Convenience function that uses the global notification manager.
    """
    global _notification_manager, _notification_cache
    if _notification_manager is None:
        print("Warning: Notification manager not initialized")
        return False
    
    # Create unique cache key for deduplication
    cache_key = f"{strategy_name}_{signal}_{execution_time.strftime('%Y%m%d_%H%M')}"
    current_time = execution_time.timestamp()
    
    # Check if this notification was already sent recently
    if cache_key in _notification_cache:
        if current_time - _notification_cache[cache_key] < _DEDUPLICATION_WINDOW:
            return True  # Skip duplicate
    
    # Update cache
    _notification_cache[cache_key] = current_time
    
    # Clean old entries from cache
    old_keys = [k for k, t in _notification_cache.items() 
                if current_time - t > _DEDUPLICATION_WINDOW]
    for k in old_keys:
        del _notification_cache[k]
    
    return _notification_manager.send_strategy_summary(
        strategy_name=strategy_name,
        execution_time=execution_time,
        signal=signal,
        position_size=position_size,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        bars_held=bars_held,
        profitable_closes=profitable_closes,
        error=error,
        indicators=indicators
    )


def notify_system(message: str, level: str = "INFO", timestamp: Optional[datetime] = None) -> bool:
    """
    Send system-level notification.
    
    Convenience function that uses the global notification manager.
    """
    global _notification_manager, _startup_notification_sent, _notification_cache
    if _notification_manager is None:
        print("Warning: Notification manager not initialized")
        return False
    
    # Create unique cache key for deduplication
    timestamp = timestamp or datetime.now()
    cache_key = f"system_{level}_{message[:50]}_{timestamp.strftime('%Y%m%d_%H%M')}"
    current_time = timestamp.timestamp()
    
    # Check if this notification was already sent recently
    if cache_key in _notification_cache:
        if current_time - _notification_cache[cache_key] < _DEDUPLICATION_WINDOW:
            return True  # Skip duplicate
    
    # Update cache
    _notification_cache[cache_key] = current_time
    
    # Clean old entries from cache
    old_keys = [k for k, t in _notification_cache.items() 
                if current_time - t > _DEDUPLICATION_WINDOW]
    for k in old_keys:
        del _notification_cache[k]
    
    # Prevent duplicate startup notifications
    if "started" in message and _startup_notification_sent:
        return True
    
    result = _notification_manager.send_system_notification(
        message=message,
        level=level,
        timestamp=timestamp
    )
    
    # Mark startup notification as sent
    if "started" in message and result:
        _startup_notification_sent = True
    
    return result
