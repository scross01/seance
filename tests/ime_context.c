/* Deterministic IME signal sequences, driven by real GTK key events.
 * Preload only into the test app; no production test hooks or desktop daemon.
 * F6 starts preedit, F7 ends/commits it, F8 commits and continues (Hangul),
 * F9 commits asynchronously, and F10 records the candidate popup anchor.
 */
#include <gtk/gtk.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    GtkIMContext parent;
    const char *preedit;
    gboolean focused;
    GdkRectangle cursor;
} TestIMContext;

typedef GtkIMContextClass TestIMContextClass;
G_DEFINE_TYPE(TestIMContext, test_im_context, GTK_TYPE_IM_CONTEXT)

static void preedit(GtkIMContext *ctx, char **text, PangoAttrList **attrs, int *pos) {
    TestIMContext *self = (TestIMContext *)ctx;
    *text = g_strdup(self->preedit);
    if (attrs) *attrs = pango_attr_list_new();
    if (pos) *pos = g_utf8_strlen(self->preedit, -1);
}

static void reset(GtkIMContext *ctx) {
    TestIMContext *self = (TestIMContext *)ctx;
    if (!*self->preedit) return;
    self->preedit = "";
    g_signal_emit_by_name(ctx, "preedit-changed");
    g_signal_emit_by_name(ctx, "preedit-end");
}

static void focus_in(GtkIMContext *ctx) {
    ((TestIMContext *)ctx)->focused = TRUE;
}

static void focus_out(GtkIMContext *ctx) {
    ((TestIMContext *)ctx)->focused = FALSE;
}

static void cursor_location(GtkIMContext *ctx, GdkRectangle *rect) {
    ((TestIMContext *)ctx)->cursor = *rect;
}

static gboolean commit_async(gpointer data) {
    GString *text = g_string_new(NULL);
    for (int i = 0; i < 128; ++i) g_string_append(text, "한글");
    g_signal_emit_by_name(data, "commit", text->str);
    g_string_free(text, TRUE);
    return G_SOURCE_REMOVE;
}

static gboolean filter(GtkIMContext *ctx, GdkEvent *event) {
    TestIMContext *self = (TestIMContext *)ctx;
    guint key = gdk_key_event_get_keyval(event);
    if (key == GDK_KEY_F10 && gdk_event_get_event_type(event) == GDK_KEY_PRESS) {
        FILE *log = fopen(g_getenv("SEANCE_TEST_IME_LOG"), "a");
        if (log) {
            fprintf(log, "%d %d %d %d %d\n", self->focused,
                    self->cursor.x, self->cursor.y, self->cursor.width, self->cursor.height);
            fclose(log);
        }
    }
    if (key >= GDK_KEY_F6 && key <= GDK_KEY_F10) {
        if (gdk_event_get_event_type(event) == GDK_KEY_RELEASE) return TRUE;
        switch (key) {
        case GDK_KEY_F6:
            self->preedit = "ㅎ";
            g_signal_emit_by_name(ctx, "preedit-start");
            g_signal_emit_by_name(ctx, "preedit-changed");
            break;
        case GDK_KEY_F7: {
            const char *text = strcmp(self->preedit, "녕") == 0 ? "녕" : "한";
            reset(ctx);  /* GTK Simple ends preedit before committing. */
            g_signal_emit_by_name(ctx, "commit", text);
            break;
        }
        case GDK_KEY_F8:
            /* Hangul engines can commit one syllable and start the next
             * with only preedit-changed, without another preedit-start. */
            g_signal_emit_by_name(ctx, "commit", "안");
            self->preedit = "녕";
            g_signal_emit_by_name(ctx, "preedit-changed");
            break;
        case GDK_KEY_F9:
            g_idle_add_full(G_PRIORITY_DEFAULT_IDLE, commit_async,
                            g_object_ref(ctx), g_object_unref);
            break;
        default:
            break;
        }
        return TRUE;
    }
    if (gdk_event_get_event_type(event) == GDK_KEY_PRESS && key == GDK_KEY_q) {
        /* A key translation distinct from the keysym detects lost im_buf text. */
        g_signal_emit_by_name(ctx, "commit", "λ");
        return TRUE;
    }
    return FALSE;
}

static void test_im_context_class_init(TestIMContextClass *klass) {
    klass->filter_keypress = filter;
    klass->get_preedit_string = preedit;
    klass->focus_in = focus_in;
    klass->focus_out = focus_out;
    klass->reset = reset;
    klass->set_cursor_location = cursor_location;
}

static void test_im_context_init(TestIMContext *self) {
    self->preedit = "";
}

GtkIMContext *gtk_im_multicontext_new(void) {
    return g_object_new(test_im_context_get_type(), NULL);
}
