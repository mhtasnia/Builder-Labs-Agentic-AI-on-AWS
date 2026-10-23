from strands import Agent, tool
import boto3
from strands.models import BedrockModel

use1_session = boto3.Session(region_name="us-east-1")
usw2_session = boto3.Session(region_name="us-west-2")
nova_lite = BedrockModel(model_id="amazon.nova-lite-v1:0", boto_session=use1_session)


@tool
def alarms(alarm_name: str) -> str:
    try:
        cloudwatch_use1 = use1_session.client("cloudwatch")
        cloudwatch_usw2 = usw2_session.client("cloudwatch")

        response_use1 = cloudwatch_use1.describe_alarms(StateValue="ALARM")
        response_usw2 = cloudwatch_usw2.describe_alarms(StateValue="ALARM")

        MetricAlarms = (
            cloudwatch_use1.describe_alarms(StateValue="ALARM")["MetricAlarms"]
            + cloudwatch_usw2.describe_alarms(StateValue="ALARM")["MetricAlarms"]
        )

        if not MetricAlarms:
            return "No alarms are currently in ALARM state"

        alarm_count = len(MetricAlarms)
        alarm_names = [alarm["AlarmName"] for alarm in MetricAlarms]

        return f"{alarm_count} alarm{'s' if alarm_count > 1 else ''} in ALARM state: {', '.join(alarm_names)}"

    except:
        return "An error occurred checking alarm with boto3"


def alarm_manager(query: str) -> str:
    try:
        alarm_manager_agent = Agent(
            model=nova_lite,
            system_prompt="You are a helpful assistant that notifies when CloudWatch alarms are in alarm",
            tools=[
                alarms,
            ],
        )
        # Call the agent and return its response
        response = alarm_manager_agent(query)

        return str(response)
    except Exception as e:
        return f"Error with alarms: {str(e)}"
