const tracker = {
  filename: 'pyproject.toml',
  updater: require('./updater.js')
}

module.exports = {
  bumpFiles: [tracker],
  packageFiles: [tracker],
  types: [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "docs", "section": "Documentation"},
    {"type": "chore", "hidden": true},
    {"type": "style", "hidden": true},
    {"type": "refactor", "hidden": true},
    {"type": "perf", "hidden": true},
    {"type": "test", "hidden": true}
  ]
}
