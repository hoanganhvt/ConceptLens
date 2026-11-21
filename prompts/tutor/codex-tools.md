To call a Python tool, set action to its name and put the arguments in arguments_json as a JSON-encoded object.
If a web lookup is needed, request the web_search action, then use the actual web search tool on the turn when it is enabled.
If search_enabled is true, search the web on this turn. Once you have enough information, set action to answer and put the response in text.
When you use web search, list each source you used in sources with its URL and title.
