# Windows Server Deployment Guide
## Trading Framework - MGC Pullback Strategy

### Overview
This guide covers deploying the trading framework on a Windows Server and scheduling the MGC pullback strategy to run daily at 4:57 PM local time.

### Prerequisites

#### 1. Windows Server Requirements
- Windows Server 2016 or later (or Windows 10/11)
- Administrative privileges
- Stable internet connection
- 2GB+ RAM minimum
- 10GB+ free disk space

#### 2. Software Requirements
- Python 3.8+ (recommended 3.9 or 3.10)
- Interactive Brokers Gateway (latest version)
- Git (for code deployment)

#### 3. IBKR Account Requirements
- Paper trading account enabled
- Market data subscription for Gold futures (GC)
- API access enabled

---

## Step 1: Install Python Environment

### 1.1 Install Python
1. Download Python from https://www.python.org/downloads/
2. Run installer with "Add Python to PATH" checked
3. Verify installation:
```cmd
python --version
pip --version
```

### 1.2 Create Virtual Environment
```cmd
# Create deployment directory
mkdir C:\TradingFramework
cd C:\TradingFramework

# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate
```

### 1.3 Install Dependencies
```cmd
# Upgrade pip
python -m pip install --upgrade pip

# Install required packages
pip install pandas ib_insync
```

---

## Step 2: Deploy Trading Framework Code

### 2.1 Copy Code Files
1. Copy the entire trading framework folder to `C:\TradingFramework\`
2. Ensure the structure looks like:
```
C:\TradingFramework\
    main.py
    config\
        settings.py
        __init__.py
    strategies\
        mgc_pullback.py
        base_strategy.py
    execution\
        broker.py
        order_manager.py
    database\
        manager.py
    utils\
        logger.py
        indicators.py
    data\
        (this will be created automatically)
    logs\
        (this will be created automatically)
```

### 2.2 Verify Configuration
Check `config/settings.py` contains:
- IBKR connection details (host: 127.0.0.1, port: 4002)
- Correct account number
- MGC contract specifications

---

## Step 3: Configure IB Gateway

### 3.1 Install IB Gateway
1. Download IB Gateway from Interactive Brokers website
2. Install with default settings
3. Create desktop shortcut for easy access

### 3.2 Configure Gateway Settings
1. Launch IB Gateway
2. Login with your paper trading account
3. Configure API settings:
   - Enable ActiveX and Socket Clients
   - Socket port: 4002 (for paper trading)
   - Allow connections from localhost
   - Read-Only API: NO (for trading)

### 3.3 Market Data Subscriptions
Ensure you have market data for:
- COMEX Gold futures (GC)
- Real-time data preferred, delayed data acceptable

### 3.4 Auto-Start Configuration
1. Create Windows service or startup shortcut
2. Configure auto-login if needed
3. Test that Gateway starts automatically

---

## Step 4: Create Batch Scripts

### 4.1 Main Trading Script
Create `C:\TradingFramework\run_mgc_strategy.bat`:

```batch
@echo off
echo Starting MGC Pullback Strategy
cd /d C:\TradingFramework

REM Activate virtual environment
call venv\Scripts\activate

REM Run the strategy
python main.py --strategy mgc

REM Keep window open for error viewing
pause
```

### 4.2 Test Script
Create `C:\TradingFramework\test_connection.bat`:

```batch
@echo off
echo Testing IB Connection
cd /d C:\TradingFramework

REM Activate virtual environment
call venv\Scripts\activate

REM Test with dry run
python main.py --strategy mgc --dry-run

pause
```

---

## Step 5: Schedule with Windows Task Scheduler

### 5.1 Open Task Scheduler
1. Press `Win + R`, type `taskschd.msc`, press Enter
2. Click "Create Task" in the Actions pane

### 5.2 General Settings
- **Name**: `MGC Pullback Strategy`
- **Description**: `Run MGC pullback trading strategy daily at 4:57 PM`
- **Security options**: 
  - Select "Run whether user is logged on or not"
  - Check "Run with highest privileges"
  - Select your Windows user account

### 5.3 Trigger Settings
1. Click "Triggers" tab
2. Click "New..."
3. Configure:
   - **Begin the task**: On a schedule
   - **Settings**: Daily
   - **Start time**: 4:57:00 PM
   - **Repeat task every**: 1 day
4. Click "OK"

### 5.4 Action Settings
1. Click "Actions" tab
2. Click "New..."
3. Configure:
   - **Action**: Start a program
   - **Program/script**: `C:\TradingFramework\run_mgc_strategy.bat`
4. Click "OK"

### 5.5 Conditions Settings
1. Click "Conditions" tab
2. Uncheck "Start the task only if the computer is on AC power"
3. Keep other settings as default

### 5.6 Settings Tab
1. Click "Settings" tab
2. Configure:
   - **Allow task to be run on demand**: Checked
   - **Stop the task if it runs longer than**: 30 minutes
   - **If the running task does not end when requested, force it to stop**: Checked
3. Click "OK"

---

## Step 6: Testing and Monitoring

### 6.1 Test Manual Execution
1. Open Command Prompt
2. Navigate to `C:\TradingFramework`
3. Run: `test_connection.bat`
4. Verify IB connection and strategy execution

### 6.2 Test Scheduled Task
1. In Task Scheduler, right-click the task
2. Select "Run"
3. Monitor execution in Task Scheduler History

### 6.3 Monitor Logs
Check log files in `C:\TradingFramework\logs\`:
- `trading.log` - Main application logs
- `strategy.mgc_pullback.log` - Strategy-specific logs

### 6.4 Database Monitoring
Check `C:\TradingFramework\data\trading.db` for:
- Signal records
- Trade executions
- Position snapshots

---

## Step 7: Maintenance and Troubleshooting

### 7.1 Daily Checklist
- IB Gateway is running and connected
- Task Scheduler task is enabled
- Log files are being updated
- No error messages in Task Scheduler

### 7.2 Common Issues
- **IB Connection Failed**: Restart IB Gateway, check API settings
- **Market Data Errors**: Verify data subscriptions
- **Task Not Running**: Check Task Scheduler service status
- **Python Errors**: Review log files for dependency issues

### 7.3 Backup Strategy
1. Back up `C:\TradingFramework\` folder weekly
2. Export Task Scheduler task configuration
3. Document any configuration changes

---

## Step 8: Security Considerations

### 8.1 Account Security
- Use strong password for Windows account
- Enable Windows Firewall
- Regular IB password changes

### 8.2 API Security
- Restrict API connections to localhost
- Monitor for unauthorized API access
- Use paper trading account for testing

### 8.3 Data Protection
- Regular database backups
- Secure log file storage
- Monitor disk space usage

---

## Emergency Procedures

### If Strategy Fails
1. Check IB Gateway connection
2. Review error logs
3. Run manual test with `test_connection.bat`
4. Restart Windows Task Scheduler service if needed

### If Server Reboots
1. Verify IB Gateway auto-start
2. Check Task Scheduler service
3. Run manual strategy test
4. Monitor next scheduled execution

---

## Contact and Support

- IBKR Technical Support: For Gateway/API issues
- System Administrator: For Windows server issues
- Development Team: For strategy code issues

---

**Last Updated**: [Current Date]
**Version**: 1.0
**Strategy**: MGC Pullback
**Schedule**: Daily at 4:57 PM Local Time
