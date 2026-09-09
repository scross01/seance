/* Observe GTK's actual fullscreen state and allocated header height.
 * Preloaded only into the test app; leaves input and window management intact.
 */
#define GDK_DISABLE_DEPRECATION_WARNINGS
#include <adwaita.h>
#include <gdk/x11/gdkx.h>

static gboolean fullscreen_label(GtkWidget *widget) {
    if (GTK_IS_LABEL(widget) &&
        g_strcmp0(gtk_label_get_text(GTK_LABEL(widget)), "Toggle Fullscreen") == 0) return TRUE;
    for (GtkWidget *child = gtk_widget_get_first_child(widget); child;
         child = gtk_widget_get_next_sibling(child)) {
        if (fullscreen_label(child)) return TRUE;
    }
    return FALSE;
}

static gboolean fullscreen_selected(GtkWidget *widget) {
    if (!gtk_widget_get_mapped(widget)) return FALSE;
    if (GTK_IS_LIST_BOX(widget)) {
        GtkListBoxRow *row = gtk_list_box_get_selected_row(GTK_LIST_BOX(widget));
        if (row && fullscreen_label(GTK_WIDGET(row))) return TRUE;
    }
    for (GtkWidget *child = gtk_widget_get_first_child(widget); child;
         child = gtk_widget_get_next_sibling(child)) {
        if (fullscreen_selected(child)) return TRUE;
    }
    return FALSE;
}

static gboolean snapshot(gpointer data) {
    (void)data;
    GListModel *windows = gtk_window_get_toplevels();
    GString *json = g_string_new("{");
    const char *separator = "";
    for (guint i = 0; i < g_list_model_get_n_items(windows); ++i) {
        GtkWindow *window = g_list_model_get_item(windows, i);
        GdkSurface *surface = gtk_native_get_surface(GTK_NATIVE(window));
        if (ADW_IS_APPLICATION_WINDOW(window) && GDK_IS_X11_SURFACE(surface)) {
            GtkWidget *content = adw_application_window_get_content(ADW_APPLICATION_WINDOW(window));
            int height = ADW_IS_TOOLBAR_VIEW(content)
                ? adw_toolbar_view_get_top_bar_height(ADW_TOOLBAR_VIEW(content)) : -1;
            GtkWidget *focus = gtk_window_get_focus(window);
            gboolean search_focused = focus && gtk_widget_get_ancestor(focus, GTK_TYPE_SEARCH_ENTRY);
            g_string_append_printf(json, "%s\"%lu\":{\"fullscreen\":%d,\"header_height\":%d,"
                                   "\"search_focused\":%d,\"fullscreen_selected\":%d}",
                                   separator, gdk_x11_surface_get_xid(surface),
                                   gtk_window_is_fullscreen(window), height,
                                   search_focused, fullscreen_selected(GTK_WIDGET(window)));
            separator = ",";
        }
        g_object_unref(window);
    }
    g_string_append(json, "}");
    g_file_set_contents(g_getenv("SEANCE_TEST_WINDOW_STATE"), json->str, json->len, NULL);
    g_string_free(json, TRUE);
    return G_SOURCE_CONTINUE;
}

__attribute__((constructor)) static void init(void) {
    if (g_getenv("SEANCE_TEST_WINDOW_STATE")) g_timeout_add(50, snapshot, NULL);
}
