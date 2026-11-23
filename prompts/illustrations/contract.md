Write all learner-facing text in {language}. Design each illustration around its learning objective. Set section to the zero-based index of the section it accompanies.

Choose one thing the learner should notice. Make it visible in the first frame through objects, their positions, sizes or directions, or the shape of a graph.
Keep the scene simple and give it life through one visible change that explains the concept. For an example about movement, animate the relevant objects themselves. Use intermediate positions so learners can follow the motion, with arrows or labels as supporting cues. For a concept without physical motion, move a marker, grow a bar, or reveal a step when that helps explain the idea.
Place short labels beside the features they describe and include units on scales. Use legible text and strong contrast on small screens. Pair color with shape, labels, or line styles to distinguish objects.

Build each illustration with HTML, CSS, and ES5 JavaScript. Do not access the DOM or network, load libraries, or use timers.
The host calls render(t,s,v,k) on each interaction and provides text(id,value) and attr(id,name,value).
Allowed elements are div, span, p, strong, svg, g, line, rect, circle, path, text, and polyline. Use IDs to identify elements.
For HTML and SVG, use only the attributes in the next line plus id, class, viewBox, stroke-width, font-size, and text-anchor. The host provides the accessible name for the illustration frame.
Attributes that can be updated are x, y, cx, cy, x1, x2, y1, y2, width, height, r, d, points, fill, stroke, opacity, and transform.
For CSS, use simple ID, class, or tag selectors and properties for color, font size, spacing, and borders.

In interactive mode, the host provides one slider with k ranging from 0 to 100. For an event such as a collision, use it to scrub from the start through the event to the result. Compute positions from k on every render and update SVG coordinates or transforms with attr. For example, show one cart rolling toward a stationary cart, the two touching, and then both continuing together at their shared velocity in a sticking collision. Let the learner scrub back and replay the same motion.
In motion mode, k is the position normalized to the range 0 to 100 across the entire trajectory. Use the values supplied by Python for t (seconds), s (meters), and v (meters per second). The host provides the graph, time control, acceleration, initial velocity, and playback. Do not recalculate the kinematics in JavaScript.
In instruction, tell the learner what to predict, what to adjust, and what to watch. Write explanation so it also makes sense if the illustration fails to render.
