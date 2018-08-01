#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>

/* DISCLAIMER:
 * This is a My First C Program, and naiveley coded, but hopefully relatively
 * bug-free. I was just happy it worked.
*/

#define BUFFER_SIZE_DEFAULT 65535
const char *USAGE = "Usage: $ readsfq [options] reads.fq\n"
"       $ gunzip -c reads.fq.gz | readsfq [options]\n"
"This will count the number of reads in a FASTQ file, giving an accurate count\n"
"even for files with multi-line reads.\n"
"Options:\n"
"-B [buffer_size]: Specify a file reading buffer size, in bytes. Default: 65535\n"
"                  WARNING: Lines longer than this will end up truncated.";

int line_is_empty(char *line);
void die(const char *message, ...);
int is_int(const char *int_str);
long count_chars(char *buffer, size_t buffer_size);

//TODO: bool
typedef enum {
  HEADER, SEQ, PLUS, QUAL
} State;

int main(int argc, char *argv[]) {

  size_t buffer_size = BUFFER_SIZE_DEFAULT;

  // Read arguments
  FILE *infile = stdin;
  char read_opt = '\0';
  int i;
  for (i = 1; i < argc; i++) {
    if (strcmp(argv[i], "-h") == 0) {
      die(USAGE);
    } else if (strcmp(argv[i], "-B") == 0) {
      read_opt = 'B';
    } else if (read_opt == 'B') {
      if (! is_int(argv[i])) {
        die("Invalid buffer size: \"%s\"", argv[i]);
      }
      buffer_size = atoi(argv[i]);
      read_opt = '\0';
    } else if (infile == stdin) {
      infile = fopen(argv[i], "r");
      if (errno) {
        die("\"%s\"", argv[i]);
      }
    } else {
      //TODO: allow any number of input files
      die("Can only process one file argument");
    }
  }

  /*TODO: This assumes that there will be at least as many quality scores as there are sequence
   *      bases. According to Dan, we can't make that assumption.
   *      Then what do we do to tell when the quality lines have ended?
   *      Ideas for disambiguating:
   *      1. If len(qual) >= len(seq), it's a NAME (If we've already seen enough
   *         quality values to cover the read, the QUAL lines must be over.)
   *      2. If the line plus the observed quality values so far is longer than the
   *         read, it must be a NAME line.
   *      3. No FASTQ format uses space characters for quality scores, according to
   *         Wikipedia. If there's a space character in the line, say it's a NAME line?
   *      But there could still conceivably be a read with truncated quality scores,
   *      followed by a NAME line that contains no spaces and is short enough to not
   *      exceed the read length.
   *      Conclusion: Just check how BioPython does it:
   *      http://biopython.org/DIST/docs/api/Bio.SeqIO.QualityIO-pysrc.html
   */

  char *line = malloc(buffer_size);

  long num_reads = 0;
  long seq_len = 0;
  long qual_len = 0;
  State state = HEADER;
  // fgets() reads a line at a time.
  char *result = fgets(line, buffer_size, infile);
  long line_num = 0;
  while (result != NULL) {
    line_num++;
    if (state == HEADER) {
      // Allow empty lines before the header.
      if (! line_is_empty(line)) {
        if (line[0] != '@') {
          die("Line %ld looked like a header line but does not start with \"@\".", line_num);
        }
        num_reads++;
        seq_len = 0;
        state = SEQ;
      }
    } else if (state == SEQ) {
      if (line[0] == '+') {
        qual_len = 0;
        state = PLUS;
      } else {
        seq_len += count_chars(line, buffer_size);
      }
    } else if (state == PLUS || state == QUAL) {
      if (state == QUAL && line[0] == '@') {
        fprintf(stderr, "Warning: Looking for more quality scores on line %ld but it starts with "
                        "\"@\".\nThis might be a header line and there were fewer quality scores "
                        "than bases.\n", line_num);
      }
      state = QUAL;
      qual_len += count_chars(line, buffer_size);
      if (qual_len >= seq_len) {
        state = HEADER;
        if (qual_len > seq_len) {
          fprintf(stderr, "Warning on line %ld: Counted more quality scores than bases.\n", line_num);
        }
      }
    }
    result = fgets(line, buffer_size, infile);
  }

  printf("%ld\n", num_reads);

  fclose(infile);
  return 0;
}


int line_is_empty(char *line) {
  switch (line[0]) {
    case '\0':
      // Empty string.
      return 1;
    case '\n':
      switch (line[1]) {
        case '\0':
          // Empty unix line.
          return 1;
      }
    case '\r':
      switch (line[1]) {
        case '\0':
          // Empty mac line.
          return 1;
        case '\n':
          if (line[2] == '\0') {
            // Empty dos line.
            return 1;
          }
      }
  }
  return 0;
}


// Count the number of content characters in the line.
// E.g. count the number of characters before any null, newline, or the end of the buffer.
long count_chars(char *buffer, size_t buffer_size) {
  long i = 0;
  while (i < buffer_size && buffer[i] != '\n' && buffer[i] != '\r' && buffer[i] != '\0') {
    i++;
  }
  return i;
}


void die(const char *message, ...) {
  const char template[] = "Error: %s";
  size_t length = strlen(message) + strlen(template) - strlen("%s") + 1;
  // get argument list
  va_list data;
  va_start(data, message);
  // copy message into template
  char final_str[length];
  sprintf(final_str, template, message);
  // print to stderr and exit
  vfprintf(stderr, final_str, data);
  if (errno) {
    perror(" ");
  } else {
    fprintf(stderr, "\n");
  }
  exit(1);
}


/* Check if a string is a valid integer. Return 0 if invalid, 1 otherwise.
 * Checks if any character is outside the ASCII range '0' to '9', or if it's
 * greater than 10 digits (will overflow a 32-bit int).
 */
int is_int(const char *int_str) {
  size_t length = strlen(int_str);
  // If the string is empty or there are more than 10 digits (length of 2^32).
  // This won't catch all int overflows, but it won't false positive.
  if (length <= 0 || length > 10) {
    return 0;
  }
  int i;
  for (i = 0; i < length; i++) {
    // If the character's ASCII value is outside the "0" to "9" range.
    if (int_str[i] < 48 || int_str[i] > 57) {
      return 0;
    }
  }
  return 1;
}