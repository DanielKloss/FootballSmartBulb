import RPi.GPIO as GPIO
import http.client
import json
import datetime
from time import sleep
from crontab import CronTab

from unittest.mock import MagicMock
import unittest

class ConfigReader():
  def __init__(self):
    configFile = open("/home/pi/FootballSmartBulb/flashingLightConfig.txt", "r")
    self.configLines = configFile.readlines()
  
  def getTeam(self):
    return self.configLines[1].rstrip()

  def getKey(self):
    return self.configLines[0].rstrip()

class Logger():
  fileName = "/home/pi/FootballSmartBulb/logs/" + str(datetime.date.today()) + ".txt"

  def writeLog(self, message):
    file = open(self.fileName, 'a')
    file.write(message + " {" + str(datetime.datetime.now()) + "}" + "\n")

class HttpRequester():
    def __init__(self, key, logger):
        self.logger = logger
        self.host = "v3.football.api-sports.io"
        self.key = key

    def makeRequest(self, request):
        conn = http.client.HTTPSConnection(self.host)
        headers = {
            'x-rapidapi-host': self.host,
            'x-rapidapi-key': self.key
        }
        try:
          conn.request("GET", request, headers=headers)
          res = conn.getresponse()
          data = res.read()
          jsonedData = json.loads(data)
          return jsonedData["response"]
        except:
          return ""

class FixtureManager():
    season = None
    fixtureStartTime = None
    fixtureId = None

    def __init__(self, httpRequester, logger):
        self.httpRequester = httpRequester
        self.logger = logger

    def checkSeason(self, currentYear, currentMonth):
      if currentMonth < 6:
        self.season = currentYear-1
      else:
        self.season = currentYear

    def checkFixtures(self, teamId):
        self.logger.writeLog("Checking fixtures")
        fixtures = self.httpRequester.makeRequest("/fixtures?team="+teamId+"&season="+str(self.season)+"&timezone=Europe/london")
        if fixtures == "":
            self.logger.writeLog("Error getting data")
            return False
        else:
            for fixture in fixtures:
              fixtureDate = datetime.datetime.strptime(fixture["fixture"]["date"],'%Y-%m-%dT%H:%M:%S%z')
              if fixtureDate.date() == datetime.date.today():
                  if fixtureDate.time() > datetime.datetime.now().time():
                      self.fixtureStartTime = fixtureDate.time()
                      self.fixtureId = fixture["fixture"]["id"]
                      self.logger.writeLog("fixture Today! at " + str(self.fixtureStartTime) + " id: " + str(self.fixtureId))
                      return True
                  else:
                      self.logger.writeLog("fixture already started")
                      return False
            self.logger.writeLog("No fixture today")
            return False

class GoalManager():
    def __init__(self, httpRequester, logger):
        self.httpRequester = httpRequester
        self.logger = logger

    def getGoals(self, teamId, fixtureId):
      goals = self.httpRequester.makeRequest("/fixtures/events?fixture="+fixtureId+"&team="+teamId+"&type=goal")
      self.logger.writeLog("Checked for goal: " + str(goals))
      if goals == "":
          self.logger.writeLog("Error getting data")
          return "error"
      else:
        for goal in goals:
          if goal["detail"] == "Missed Penalty":
            goals.remove(goal)
        return len(goals)

class MainProgram():
  def __init__(self, fixtureManager, goalManager, logger, team):
    self.fixtureManager = fixtureManager
    self.goalManager = goalManager
    self.logger = logger
    self.team = team

  def run(self):
    GPIO.setmode(GPIO.BOARD)
    self.ledPin = 12
    GPIO.setup(self.ledPin, GPIO.OUT)

    fixtureFile = open("/home/pi/light/fixtures.txt", "r+")
    fixtureIds = fixtureFile.readlines()
    cron = CronTab(user="pi")

    if len(fixtureIds) > 0:
      goalTracker = 0
      for i in range (99):
        self.logger.writeLog("Checking for goal - Team: " + str(self.team) + " fixtureId: " + str(fixtureIds[0]))
        numberOfGoals = self.goalManager.getGoals(self.team, fixtureIds[0])
        if numberOfGoals == "error":
          self.logger.writeLog("Error getting data - will try again in 65 seconds")
          sleep(65)
          continue
        elif numberOfGoals < goalTracker:
          self.logger.writeLog("Got less goals than previous. Must be VAR disallowing goals again. Reseting number of goals back to " + numberOfGoals)
          goalTracker = numberOfGoals
        elif numberOfGoals > goalTracker:
          goalTracker = numberOfGoals
          self.logger.writeLog("TEAM SCORED!")
          for i in range(5):
            GPIO.output(self.ledPin, True)
            sleep(0.5)
            GPIO.output(self.ledPin, False)
            sleep(0.5)
        else:
          self.logger.writeLog("No new goal")
        sleep(65)

      cron.remove_all(comment="match")
      cron.write()
      fixtureFile.truncate(0)
      fixtureFile.close()
    else:
        self.fixtureManager.checkSeason(datetime.datetime.now().year, datetime.datetime.now().month)
        if self.fixtureManager.checkFixtures(self.team):
            fixtureFile.write(str(self.fixtureManager.fixtureId))
            self.logger.writeLog("Writing fixture to file - id: " + str(self.fixtureManager.fixtureId))
            fixtureFile.close()
            job = cron.new(command="/usr/bin/python3 /home/pi/FootballSmartBulb/flashingLight.py", comment="match")
            job.setall(str(self.fixtureManager.fixtureStartTime.minute), str(self.fixtureManager.fixtureStartTime.hour), '*', '*', '*')
            self.logger.writeLog("Writing Cron Job - minute: " + str(self.fixtureManager.fixtureStartTime.minute) + " hour: " + str(self.fixtureManager.fixtureStartTime.hour))
            cron.write()

class FixtureManagerTests(unittest.TestCase):
  MockHttp = MagicMock()
  MockLogger = MagicMock()

  def test_FixtureToday_MakeRequest_Called(self):
    self.MockHttp.makeRequest.return_value = ""
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    fixtureManager.checkFixtures("40")
    self.MockHttp.makeRequest.assert_called()

  def test_FixtureToday_NoFixture_ReturnsFalse(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"fixture\": {\"id\": 592225, \"date\": \"2020-11-24T15:00:00+00:00\"}}]")
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    self.assertEqual(fixtureManager.checkFixtures("40"), False)

  def test_FixtureToday_Fixture_ReturnsTrue(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"fixture\": {\"id\": 592225, \"date\": \""+str(datetime.date.today())+"T23:59:59+00:00\"}}]")
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    self.assertEqual(fixtureManager.checkFixtures("40"), True)

  def test_FixtureToday_Fixture_SetsFixtureId(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"fixture\": {\"id\": 592225, \"date\": \""+str(datetime.date.today())+"T23:59:59+00:00\"}}]")
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    fixtureManager.checkFixtures("40")
    self.assertEqual(fixtureManager.fixtureId, 592225)

  def test_FixtureToday_Fixture_SetsFixtureStartTime(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"fixture\": {\"id\": 592225, \"date\": \""+str(datetime.date.today())+"T23:59:59+00:00\"}}]")
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    fixtureManager.checkFixtures("40")
    self.assertEqual(fixtureManager.fixtureStartTime, datetime.time(23,59,59))

  def test_FixtureToday_Error_ReturnsFalse(self):
    self.MockHttp.makeRequest.return_value = ""
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    self.assertEqual(fixtureManager.checkFixtures("40"), False)

  def test_FixtureToday_FixtureAlreadyStarted_ReturnsFalse(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"fixture\": {\"id\": 592225, \"date\": \""+str(datetime.date.today())+"T00:00:00+00:00\"}}]")
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    self.assertEqual(fixtureManager.checkFixtures("40"), False)


  def test_CheckSeason_Sets2020_WhenYear2020AndMonth10(self):
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    fixtureManager.checkSeason(2020, 7)
    self.assertEqual(fixtureManager.season, 2020)

  def test_CheckSeason_Sets2020_WhenYear2021AndMonth5(self):
    fixtureManager = FixtureManager(self.MockHttp, self.MockLogger)
    fixtureManager.checkSeason(2021, 5)
    self.assertEqual(fixtureManager.season, 2020)

class GoalManagerTests(unittest.TestCase):
  MockHttp = MagicMock()
  MockLogger = MagicMock()

  def test_CheckForGoals_MakeRequest_Called(self):
    self.MockHttp.makeRequest.return_value = ""
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    goalManager.checkForGoals("40", "592225", 0)
    self.MockHttp.makeRequest.assert_called()

  def test_CheckForGoals_Error_ReturnsZero(self):
    self.MockHttp.makeRequest.return_value = ""
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    self.assertEqual(goalManager.checkForGoals("40", "592225", 0), 0)

  def test_CheckForGoals_NoGoalsFromZero_ReturnsZero(self):
    self.MockHttp.makeRequest.return_value = json.loads("[]")
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    self.assertEqual(goalManager.checkForGoals("40", "592225", 0), 0)

  def test_CheckForGoals_NoGoalsFromOne_ReturnsZero(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"goal\": {\"id\": 592225}}]")
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    self.assertEqual(goalManager.checkForGoals("40", "592225", 1), 0)

  def test_CheckForGoals_OneNewGoalFromZero_ReturnsOne(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"goal\": {\"id\": 592225}}]")
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    self.assertEqual(goalManager.checkForGoals("40", "592225", 0), 1)

  def test_CheckForGoals_TwoNewGoalsFromZero_ReturnsTwo(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"goal\": {\"id\": 592225}}, {\"goal\": {\"id\": 592225}}]")
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    self.assertEqual(goalManager.checkForGoals("40", "592225", 0), 2)

  def test_CheckForGoals_OneNewGoalFromOne_ReturnsTwo(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"goal\": {\"id\": 592225}}, {\"goal\": {\"id\": 592225}}]")
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    self.assertEqual(goalManager.checkForGoals("40", "592225", 1), 1)

  def test_CheckForGoals_TwoNewGoalsFromOne_ReturnsThree(self):
    self.MockHttp.makeRequest.return_value = json.loads("[{\"goal\": {\"id\": 592225}}, {\"goal\": {\"id\": 592225}}, {\"goal\": {\"id\": 592225}}]")
    goalManager = GoalManager(self.MockHttp, self.MockLogger)
    self.assertEqual(goalManager.checkForGoals("40", "592225", 1), 2)

logger = Logger()
configReader = ConfigReader()
key = configReader.getKey()
team = configReader.getTeam()
httpRequester = HttpRequester(key, logger)
goalManager = GoalManager(httpRequester, logger)
fixtureManager = FixtureManager(httpRequester, logger)
mainProgram = MainProgram(fixtureManager, goalManager, logger, team)
mainProgram.run()
#unittest.main(verbosity=2, exit=False)
