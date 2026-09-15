Always follow these instructions before writing code.

- Always read official documentation for the libraries and frameworks you are using.
- Do not reinvent the wheel. Always check if there exists an official solution or library for a problem before implementing your own. Ask me clarifying questions if needed.
- Follow PEP 8 (https://peps.python.org/pep-0008/) standards for Python code, including naming conventions, organising import at top level, indentation, and line length, and using proper spacing around operators and after commas.
- Write tests to verify the behavior of your code, especially for critical functionality.
- Use structured logging to make your logs more aggregator-friendly and easier to analyze.
- Write meaningful comments and documentation to explain the purpose and behavior of your code.
- Follow engineering best practices like SOLID principles, DRY (Don't Repeat Yourself), and KISS (Keep It Simple, Stupid) and suitable standard design patterns to solve a problem.
- Keep your code modular and reusable by breaking it down into smaller, well-defined functions and classes.
- Suggest areas that can be improved or optimized in the code.
- The project has both mock and real tools. Mock tools are only for testing and development purposes, while real tools are used in production to interact with actual services. Consider real tool implementation whenever you are trying to understand the codebase.
- Always keep hardcoded strings and numeric values in central config, well documented, and avoid scattering them throughout the code. This makes the code easier to maintain and update.
- Variable and method names should be self-explanatory. Do not shorten the variable names like "dep" for "departure" or "ret" for "return_date".
- Always prefer descriptive names for classes, functions, and variables to improve code readability and maintainability.