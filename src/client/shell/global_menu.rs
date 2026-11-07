use super::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ClientGlobalMenuAction {
    Binding(crate::input::KeybindAction),
    PluginCommand(usize),
    WhatsNew,
}

pub(super) fn global_menu_attention(snapshot: &ClientShellSnapshot) -> bool {
    snapshot.update_available.is_some() || snapshot.integration_updates_available
}

pub(super) fn global_menu_item_has_badge(
    snapshot: &ClientShellSnapshot,
    action: ClientGlobalMenuAction,
) -> bool {
    (action == ClientGlobalMenuAction::WhatsNew && snapshot.update_available.is_some())
        || (action == ClientGlobalMenuAction::Binding(crate::input::KeybindAction::Settings)
            && snapshot.integration_updates_available)
}

pub(super) fn global_menu_items(
    snapshot: &ClientShellSnapshot,
) -> Vec<(&str, ClientGlobalMenuAction)> {
    let mut items = vec![
        (
            "settings",
            ClientGlobalMenuAction::Binding(crate::input::KeybindAction::Settings),
        ),
        (
            "keybinds",
            ClientGlobalMenuAction::Binding(crate::input::KeybindAction::Help),
        ),
        (
            "reload config",
            ClientGlobalMenuAction::Binding(crate::input::KeybindAction::ReloadConfig),
        ),
    ];
    let mut seen = std::collections::HashSet::new();
    for (index, command) in snapshot.commands.iter().enumerate() {
        if command.action != crate::protocol::ClientShellCommandAction::PluginAction
            || !seen.insert(command.command_id.as_str())
        {
            continue;
        }
        items.push((
            command
                .description
                .as_deref()
                .unwrap_or(&command.command_id),
            ClientGlobalMenuAction::PluginCommand(index),
        ));
    }
    if snapshot.update_available.is_some() || snapshot.latest_release_notes_available {
        items.push((
            if snapshot.update_available.is_some() {
                "update ready"
            } else {
                "what's new"
            },
            ClientGlobalMenuAction::WhatsNew,
        ));
    }
    items.push((
        "detach",
        ClientGlobalMenuAction::Binding(crate::input::KeybindAction::Detach),
    ));
    items
}

impl ClientShellState {
    pub(super) fn toggle_global_menu(&mut self) {
        if matches!(self.overlay, Some(ClientShellOverlay::GlobalMenu(_))) {
            self.overlay = None;
        } else {
            self.overlay = Some(ClientShellOverlay::GlobalMenu(ClientGlobalMenuOverlay {
                highlighted: 0,
            }));
        }
    }

    pub(super) fn move_global_menu_selection(&mut self, delta: isize) {
        let item_count = self
            .snapshot
            .as_deref()
            .map(global_menu_items)
            .map_or(0, |items| items.len());
        let Some(ClientShellOverlay::GlobalMenu(menu)) = self.overlay.as_mut() else {
            return;
        };
        menu.highlighted = (menu.highlighted as isize + delta)
            .clamp(0, item_count.saturating_sub(1) as isize) as usize;
    }

    pub(super) fn activate_global_menu_item(
        &mut self,
        index: usize,
        outcome: &mut ClientShellInput,
    ) {
        let Some(action) = self.snapshot.as_deref().and_then(|snapshot| {
            global_menu_items(snapshot)
                .get(index)
                .map(|(_, action)| *action)
        }) else {
            return;
        };
        if action == ClientGlobalMenuAction::WhatsNew
            && self
                .snapshot
                .as_deref()
                .and_then(|snapshot| snapshot.release_notes.as_ref())
                .is_none()
        {
            return;
        }
        self.overlay = None;
        match action {
            ClientGlobalMenuAction::Binding(binding) => {
                self.record_binding(crate::input::KeybindMatch::Action(binding), outcome)
            }
            ClientGlobalMenuAction::WhatsNew => self.open_release_notes(),
            ClientGlobalMenuAction::PluginCommand(index) => {
                let Some(snapshot) = self.snapshot.as_deref() else {
                    return;
                };
                let Some(command) = snapshot.commands.get(index) else {
                    return;
                };
                let params = crate::api::schema::CommandInvokeParams {
                    command_id: command.command_id.clone(),
                    workspace_id: snapshot.focused_workspace_id.clone(),
                    tab_id: snapshot.focused_tab_id.clone(),
                    pane_id: snapshot.focused_pane_id.clone(),
                    selection: None,
                };
                self.push_endpoint_method(
                    crate::api::schema::Method::CommandInvoke(params),
                    outcome,
                );
            }
        }
        outcome.repaint = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn menu_exposes_plugin_actions_without_shell_commands_or_duplicates() {
        let mut snapshot = crate::client::shell::tests::snapshot();
        let search = crate::protocol::ClientShellCommand {
            command_id: "session-search".into(),
            binding_label: "Ctrl+B /".into(),
            binding_labels: vec!["Ctrl+B /".into()],
            action: crate::protocol::ClientShellCommandAction::PluginAction,
            description: Some("Search all agent sessions".into()),
        };
        snapshot.commands.push(search.clone());
        snapshot.commands.push(search);
        snapshot.commands.push(crate::protocol::ClientShellCommand {
            command_id: "shell".into(),
            action: crate::protocol::ClientShellCommandAction::Shell,
            ..snapshot.commands[0].clone()
        });
        let items = global_menu_items(&snapshot);
        assert_eq!(
            items
                .iter()
                .filter(|(label, _)| *label == "Search all agent sessions")
                .count(),
            1
        );
        assert!(!items
            .iter()
            .any(|(_, action)| *action == ClientGlobalMenuAction::PluginCommand(2)));
    }

    #[test]
    fn search_menu_action_invokes_the_endpoint_command_with_focused_context() {
        let mut snapshot = crate::client::shell::tests::snapshot();
        snapshot.commands.push(crate::protocol::ClientShellCommand {
            command_id: "session-search".into(),
            binding_label: String::new(),
            binding_labels: Vec::new(),
            action: crate::protocol::ClientShellCommandAction::PluginAction,
            description: Some("Search sessions".into()),
        });
        let index = global_menu_items(&snapshot)
            .iter()
            .position(|(label, _)| *label == "Search sessions")
            .unwrap();
        let mut state = ClientShellState::new(ClientShellConfig::from_config(
            &crate::config::Config::default(),
        ));
        state.set_snapshot(Box::new(snapshot));
        state.toggle_global_menu();
        let mut outcome = ClientShellInput::default();
        state.activate_global_menu_item(index, &mut outcome);
        let [ClientShellAction::Endpoint { request, .. }] = &outcome.actions[..] else {
            panic!("expected endpoint command invocation");
        };
        let crate::api::schema::Method::CommandInvoke(params) = &request.method else {
            panic!("expected command.invoke");
        };
        assert_eq!(params.command_id, "session-search");
        assert_eq!(params.workspace_id.as_deref(), Some("ws_1"));
        assert_eq!(params.pane_id.as_deref(), Some("pane_1"));
        assert!(state.overlay.is_none());
    }
}
