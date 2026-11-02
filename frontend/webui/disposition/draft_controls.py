"""Shared task Save controls; all draft data remains in the mounted ReviewForm."""
from nicegui import ui
from .messages import text


class DraftControls:
    def __init__(self,form,host):
        self.form=form
        self.dialogs=[]
        with host:
            # Native PageSticky accounts for the application footer and drawer.
            # The spacer keeps final page controls clear when the bar wraps.
            ui.element('div').classes('h-48 sm:h-28 w-full').props('aria-hidden=true')
            with ui.page_sticky(position='bottom',expand=True).classes('z-20') as self.sticky:
                with ui.card().props('flat bordered square').classes('messaging-workspace w-full gap-1 px-5 py-3'):
                    with ui.row().classes('w-full items-center justify-between gap-3 flex-wrap'):
                        with ui.row().classes('items-center gap-3'):
                            self.icon=ui.icon('check_circle_outline').classes('text-primary text-xl')
                            with ui.column().classes('gap-0'):
                                self.status=ui.label('').props('role=status')
                                ui.label(text('shared_save_hint')).classes('text-xs text-slate-600')
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            self.review=ui.button(text('review_changes'),icon='fact_check',on_click=self.show_review).props('flat no-caps')
                            self.save=ui.button(text('save_changes'),icon='save',on_click=lambda:form.perform('save')).props('no-caps')
                    self.feedback=ui.label('').props('role=alert').classes('text-negative whitespace-pre-wrap')
        self.update()

    def count(self):
        f=self.form
        return len(f.pending)+int(f.comments is not None and str(f.comments.value or '')!=f.saved_comments)

    def update(self):
        if not self.form.alive() or self.sticky._deleted:return
        with self.sticky:
            count=self.count()
            self.status.text=text('all_changes_saved') if not count else text('unsaved_change_one') if count==1 else text('unsaved_changes_count',count=count)
            self.icon.name='edit_note' if count else 'check_circle_outline'
            enabled=bool(count) and not self.form.busy
            self.save.set_enabled(enabled);self.review.set_enabled(enabled)
            self.feedback.text=self.form.feedback.text
            self.feedback.set_visibility(bool(self.feedback.text))
            self.form.draft_buttons[:]=[b for b in self.form.draft_buttons if not b._deleted]
            for button in self.form.draft_buttons:button.set_enabled(not self.form.busy)
            for dialog,button,feedback in list(self.dialogs):
                if dialog._deleted or not dialog.value:
                    self.dialogs.remove((dialog,button,feedback));continue
                button.set_enabled(enabled);feedback.text=self.form.feedback.text;feedback.set_visibility(bool(feedback.text))

    def dialog_actions(self,dialog):
        feedback=ui.label('').props('role=alert').classes('text-negative whitespace-pre-wrap')
        feedback.set_visibility(False)
        async def save():
            if await self.form.perform('save') and self.form.alive() and dialog.value:dialog.close()
        with ui.row().classes('w-full justify-end gap-2 flex-wrap'):
            ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
            button=ui.button(text('save_changes'),icon='save',on_click=save).props('no-caps')
        record=(dialog,button,feedback)
        self.dialogs.append(record)
        button.set_enabled(bool(self.count()) and not self.form.busy)
        def closed(event):
            if not event.value and record in self.dialogs:self.dialogs.remove(record)
        dialog.on_value_change(closed)

    def show_review(self):
        f=self.form
        if not f.alive() or f.busy or not self.count():return
        with ui.dialog() as dialog,ui.card().classes('messaging-workspace p-0 gap-0 flex-nowrap').style('width: 760px; max-width: calc(100vw - 32px); max-height: calc(100dvh - 48px)'):
            with ui.column().classes('w-full p-5 pb-3 gap-1 shrink-0'):
                ui.label(text('review_changes')).classes('text-xl font-semibold')
                ui.label(f.job.get('job_number') or '').props('dir=auto').classes('text-slate-600')
            body=ui.column().classes('w-full p-5 pt-0 gap-3 overflow-y-auto min-h-0')
            with ui.column().classes('w-full p-5 pt-3 gap-2 shrink-0'):
                ui.label(text('shared_save_hint')).classes('text-xs text-slate-600')
                self.dialog_actions(dialog)
        dialog.open()
        f.register_draft_disclosure(dialog,body,None)
        self.update()
