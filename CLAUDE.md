You are tasked with helping setting up a python wrapper around the fastf1 library. And setting up a flask app that visualizes historic formula 1 using a 2d mapview with car positions marked in a dynamic race simulation using telemetry data.
Focus on core aspects of what the user is asking.
Achieve the results with as little added code as possible.
Be on the lookout for code repitition that we can solve by setting up strategic helper function.
Dont spend additional time setting up documentation that havent been specifically asked for.
In stead print a minimalistic and short summary in the chat about what have been done.
Only do tests when there are parts of the code you are uncertain about, or if the user has specifically asked for tests. If in doubt ask the user if you should do tests on the code changes.
When adding data imports from fastf1 library stick as much as possible to the fastf1 api structure (outlined in fastf1_docs/)
A lot of the functionality is already implemented in a old outdated version (legacy_f1_user/). If there are valid implementations from there we can use in the updated version of the app, notify the user and implement. Remember to optimize the code for our current setup (with much improved backend code)