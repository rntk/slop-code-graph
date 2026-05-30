This is a CLI python script which generate codebase call graph. The main goal is to see the flow. Not only "happy path". But actually step by step the whole algorhytm.
- We generate an HTML file.
- Graph is a SVG with function names. Also include metadata such as: file name/module name, class name if it is a method, source code of the function. Node is function, edges is calls
- The file should be fully independend, so I can send this file to someone and they will be able to open and see the graph.
- We need to support as many languages as possible. This is why tree sitter. For the beginning lets say we support: python, js, ts, go, java, c++, php
- We need to support as single file as a directory. SHould be not such big of the diffference. If directory, we just add more root nodes to the graph if the files are not connected.
- On the page should be fuzzy search input.
- The UI is some sort of huge canvas where we can zoom in/out to any part of the graph.


1. How to run "python graph.py file_name.js -o graph.html" "python graph.py dir_name -o graph.html"