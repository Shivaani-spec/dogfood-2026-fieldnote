(function () {
  "use strict";
  var projects = [];
  var selectedId = "";
  var timer;
  var escapeHtml = function (value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  };
  var dateLabel = function (value) {
    if (!value) return "Date not supplied";
    var date = new Date(value);
    return isNaN(date.getTime()) ? "Date not supplied" : new Intl.DateTimeFormat("en", {
      day: "numeric", month: "short", year: "numeric", timeZone: "UTC"
    }).format(date);
  };
  function filteredProjects() {
    var query = document.getElementById("search").value.trim().toLocaleLowerCase();
    var track = document.getElementById("track-filter").value;
    var sort = document.getElementById("sort-order").value;
    var rows = projects.filter(function (project) {
      var matchTrack = !track || project.track === track;
      var text = [project.title, project.team, project.track, project.id].join(" ").toLocaleLowerCase();
      return matchTrack && (!query || text.indexOf(query) >= 0);
    });
    rows.sort(function (a, b) {
      if (sort === "title") return a.title.localeCompare(b.title);
      var difference = Date.parse(a.submittedAt || 0) - Date.parse(b.submittedAt || 0);
      return sort === "oldest" ? difference : -difference;
    });
    return rows;
  }
  function selectProject(id) {
    var project = projects.find(function (item) { return item.id === id; });
    if (!project) return;
    selectedId = id;
    document.querySelectorAll(".row-open").forEach(function (button) {
      button.setAttribute("aria-pressed", button.getAttribute("data-project") === id ? "true" : "false");
      var row = button.closest("tr");
      if (row) row.classList.toggle("is-selected", button.getAttribute("data-project") === id);
    });
    var summary = project.summary && project.summary !== "One line of what it does." ? project.summary : "No project narrative is included in this checker fixture.";
    document.getElementById("selected-content").innerHTML =
      '<div class="selected-project"><span class="track-label">' + escapeHtml(project.track) + '</span>' +
      '<h3 id="selected-title">' + escapeHtml(project.title) + '</h3>' +
      '<div class="detail-meta"><span>' + escapeHtml(project.team) + '</span><span>' + escapeHtml(project.id) + '</span><span>' + escapeHtml(dateLabel(project.submittedAt)) + '</span></div>' +
      '<p class="detail-copy">' + escapeHtml(summary) + ' This fictional record is provided for acceptance-checker coverage; no repository or demo link is represented here.</p></div>';
  }
  function render() {
    var rows = filteredProjects();
    document.getElementById("visible-count").textContent = rows.length + (rows.length === 1 ? " record" : " records");
    document.getElementById("submission-rows").innerHTML = rows.map(function (project) {
      return '<tr class="' + (project.id === selectedId ? "is-selected" : "") + '"><td><span class="project-name">' + escapeHtml(project.title) + '</span><span class="project-id">' + escapeHtml(project.id) + '</span></td>' +
        '<td class="team-name">' + escapeHtml(project.team) + '</td>' +
        '<td><span class="track-label">' + escapeHtml(project.track) + '</span></td>' +
        '<td class="project-id">' + escapeHtml(dateLabel(project.submittedAt)) + '</td>' +
        '<td><button class="row-open" type="button" data-project="' + escapeHtml(project.id) + '" aria-pressed="' + (project.id === selectedId ? "true" : "false") + '">Open</button></td></tr>';
    }).join("");
    document.getElementById("empty-state").hidden = rows.length > 0;
    document.querySelector(".table-wrap").hidden = rows.length === 0;
    if (!rows.some(function (project) { return project.id === selectedId; })) selectedId = rows.length ? rows[0].id : "";
    if (selectedId) selectProject(selectedId);
    else document.getElementById("selected-content").innerHTML = '<div class="detail-placeholder"><span class="placeholder-mark" aria-hidden="true">↖</span><strong id="selected-title">No entry selected</strong><p>Adjust the search or track filter to continue.</p></div>';
  }
  function showNotice(message) {
    var notice = document.getElementById("notice");
    notice.textContent = message;
    notice.classList.add("is-visible");
    clearTimeout(timer);
    timer = setTimeout(function () { notice.classList.remove("is-visible"); }, 2100);
  }
  fetch("/data.json").then(function (response) {
    if (!response.ok) throw new Error("Could not load fixture data (" + response.status + ").");
    return response.json();
  }).then(function (data) {
    projects = data.projects || [];
    var tracks = Array.from(new Set(projects.map(function (project) { return project.track; }))).sort();
    document.getElementById("metric-projects").textContent = String(projects.length).padStart(2, "0");
    document.getElementById("metric-tracks").textContent = String(tracks.length).padStart(2, "0");
    document.getElementById("track-filter").insertAdjacentHTML("beforeend", tracks.map(function (track) {
      return '<option value="' + escapeHtml(track) + '">' + escapeHtml(track) + '</option>';
    }).join(""));
    render();
    if (projects.length) selectProject(projects[0].id);
  }).catch(function (error) {
    document.getElementById("submission-rows").innerHTML = '<tr><td colspan="5" class="loading">' + escapeHtml(error.message) + '</td></tr>';
  });
  document.getElementById("search").addEventListener("input", render);
  document.getElementById("track-filter").addEventListener("change", render);
  document.getElementById("sort-order").addEventListener("change", render);
  document.getElementById("submission-rows").addEventListener("click", function (event) {
    var button = event.target.closest("[data-project]");
    if (button) selectProject(button.getAttribute("data-project"));
  });
  document.getElementById("clear-filters").addEventListener("click", function () {
    document.getElementById("search").value = "";
    document.getElementById("track-filter").value = "";
    document.getElementById("sort-order").value = "newest";
    render();
  });
  document.getElementById("copy-command").addEventListener("click", function () {
    var done = function () { showNotice("Copied: docker compose up"); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText("docker compose up").then(done).catch(function () { showNotice("Run docker compose up from the project directory."); });
    } else showNotice("Run docker compose up from the project directory.");
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      event.preventDefault();
      document.getElementById("search").focus();
    }
  });
}());
