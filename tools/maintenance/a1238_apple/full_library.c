#define _GNU_SOURCE
#include <gpod/itdb.h>
#include <glib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static gchar *decode(const char *encoded) {
    gsize bytes = 0;
    guchar *raw = g_base64_decode(encoded, &bytes);
    gchar *value = g_strndup((const gchar *)raw, bytes);
    g_free(raw);
    if (!g_utf8_validate(value, -1, NULL)) {
        g_free(value);
        return NULL;
    }
    return value;
}

static unsigned long long number(const char *value) {
    char *end = NULL;
    unsigned long long result = strtoull(value, &end, 10);
    if (!value[0] || !end || *end) {
        fprintf(stderr, "Invalid manifest number: %s\n", value);
        exit(2);
    }
    return result;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s staging-mount manifest.tsv\n", argv[0]);
        return 2;
    }
    Itdb_iTunesDB *db = itdb_new();
    itdb_set_mountpoint(db, argv[1]);
    itdb_device_set_sysinfo(db->device, "ModelNumStr", "MB147");
    itdb_device_set_sysinfo(db->device, "FirewireGuid", "0x000A2700155D9C10");
    Itdb_Playlist *master = itdb_playlist_new("iPod", FALSE);
    itdb_playlist_set_mpl(master);
    itdb_playlist_add(db, master, -1);
    FILE *input = fopen(argv[2], "rb");
    if (!input) {
        perror(argv[2]);
        return 2;
    }
    char *line = NULL;
    size_t capacity = 0;
    unsigned count = 0;
    while (getline(&line, &capacity, input) >= 0) {
        line[strcspn(line, "\r\n")] = 0;
        gchar **fields = g_strsplit(line, "\t", 0);
        if (g_strv_length(fields) != 12 || strlen(fields[0]) > 55 ||
            strncmp(fields[0], ":iPod_Control:Music:..:..:Music:", 32)) {
            fprintf(stderr, "Invalid manifest line %u\n", count + 1);
            return 2;
        }
        unsigned long long size = number(fields[1]);
        unsigned long long duration = number(fields[2]);
        unsigned long long bitrate = number(fields[3]);
        unsigned long long sample_rate = number(fields[4]);
        unsigned long long track_number = number(fields[5]);
        unsigned long long disc_number = number(fields[6]);
        if (size == 0 || size > G_MAXUINT32 || duration == 0 || duration > G_MAXINT32 ||
            bitrate > G_MAXINT32 || sample_rate == 0 || sample_rate > G_MAXUINT16 ||
            track_number > G_MAXINT32 || disc_number > G_MAXINT32) {
            fprintf(stderr, "Out-of-range metadata at line %u\n", count + 1);
            return 2;
        }
        Itdb_Track *track = itdb_track_new();
        track->ipod_path = g_strdup(fields[0]);
        track->size = (guint32)size;
        track->tracklen = (gint32)duration;
        track->bitrate = (gint32)bitrate;
        track->samplerate = (guint16)sample_rate;
        track->samplerate2 = (gdouble)track->samplerate;
        track->track_nr = (gint32)track_number;
        track->cd_nr = (gint32)disc_number;
        track->title = decode(fields[7]);
        track->artist = decode(fields[8]);
        track->album = decode(fields[9]);
        track->albumartist = decode(fields[10]);
        track->genre = decode(fields[11]);
        if (!track->title || !track->artist || !track->album ||
            !track->albumartist || !track->genre || track->size == 0 ||
            track->tracklen <= 0 || track->samplerate == 0) {
            fprintf(stderr, "Invalid metadata at line %u\n", count + 1);
            return 2;
        }
        track->filetype = g_strdup("MPEG audio file");
        track->filetype_marker = 0x4d503320;
        track->type2 = 1;
        track->mediatype = ITDB_MEDIATYPE_AUDIO;
        track->transferred = TRUE;
        itdb_track_add(db, track, -1);
        itdb_playlist_add_track(master, track, -1);
        g_strfreev(fields);
        count++;
    }
    free(line);
    fclose(input);
    if (count == 0) {
        fprintf(stderr, "Manifest has no tracks\n");
        return 2;
    }
    GError *error = NULL;
    gboolean ok = itdb_write(db, &error);
    if (!ok) fprintf(stderr, "iTunesDB write failed: %s\n", error ? error->message : "unknown");
    if (error) g_error_free(error);
    itdb_free(db);
    fprintf(stderr, "wrote %u tracks\n", count);
    return ok ? 0 : 1;
}
