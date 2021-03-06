#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import types
"""A simple parser for FASTA, FASTQ, SAM, etc. Create generators that just return the read name and
sequence.
All format parsers follow this API:
  with open('sequence.fasta') as fasta:
    for read in getreads.getparser(fasta, filetype='fasta'):
      print "There is a sequence with this FASTA identifier: "+read.id
      print "Its sequence is "+read.seq
The properties of Read are:
  name: The entire FASTA header line, SAM column 1, etc.
  id:   The first whitespace-delimited part of the name.
  seq:  The sequence.
  qual: The quality scores (unless the format is FASTA).
"""

# Available formats.
FORMATS = ('fasta', 'fastq', 'sam', 'tsv', 'lines')

QUAL_OFFSETS = {'sanger':33, 'solexa':64}


def getparser(input, filetype, qual_format='sanger', name_col=1, seq_col=2, qual_col=3):
  # Detect whether the input is an open file or a path.
  # Return the appropriate reader.
  if filetype == 'fasta':
    return FastaReader(input)
  elif filetype == 'fastq':
    return FastqReader(input, qual_format=qual_format)
  elif filetype == 'sam':
    return SamReader(input, qual_format=qual_format)
  elif filetype == 'tsv':
    return TsvReader(input, qual_format=qual_format,
                     name_col=name_col, seq_col=seq_col, qual_col=qual_col)
  elif filetype == 'lines':
    return LineReader(input)
  else:
    raise ValueError('Unrecognized format: {!r}'.format(filetype))


def detect_input_type(obj):
  """Is this an open filehandle, or is it a file path (string)?"""
  try:
    os.path.isfile(obj)
    return 'path'
  except TypeError:
    if isinstance(obj, types.GeneratorType):
      return 'generator'
    elif hasattr(obj, 'read') and hasattr(obj, 'close'):
      return 'file'
    else:
      return None


class FormatError(Exception):
  def __init__(self, message=None):
    if message:
      Exception.__init__(self, message)


class Read(object):
  def __init__(self, name='', seq='', id_='', qual='', qual_format='sanger'):
    self.name = name
    self.seq = seq
    self.id = id_
    self.qual = qual
    self.offset = QUAL_OFFSETS[qual_format]
  @property
  def scores(self):
    if self.qual is None:
      return None
    scores = []
    for qual_char in self.qual:
      scores.append(ord(qual_char) - self.offset)
    return scores


class Reader(object):
  """Base class for all other parsers."""
  def __init__(self, input, **kwargs):
    self.input = input
    self.input_type = detect_input_type(input)
    if self.input_type not in ('path', 'file', 'generator'):
      raise ValueError('Input object {!r} not a file, string, or generator.'.format(input))
    for key, value in kwargs.items():
      setattr(self, key, value)
  def __iter__(self):
    return self.parser()
  def bases(self):
    for read in self.parser():
      for base in read.seq:
        yield base
  def get_input_iterator(self):
    if self.input_type == 'path':
      return open(self.input)
    else:
      return self.input


class LineReader(Reader):
  """A parser for the simplest format: Only the sequence, one line per read."""
  def parser(self):
    input_iterator = self.get_input_iterator()
    try:
      for line in input_iterator:
        read = Read(seq=line.rstrip('\r\n'))
        yield read
    finally:
      if self.input_type == 'path':
        input_iterator.close()


class TsvReader(Reader):
  """A parser for a simple tab-delimited format.
  Column 1: name
  Column 2: sequence
  Column 3: quality scores (optional)"""
  def parser(self):
    min_fields = max(self.name_col, self.seq_col)
    input_iterator = self.get_input_iterator()
    try:
      for line in input_iterator:
        fields = line.rstrip('\r\n').split('\t')
        if len(fields) < min_fields:
          continue
        read = Read(qual_format=self.qual_format)
        read.name = fields[self.name_col-1]
        if read.name:
          read.id = read.name.split()[0]
        read.seq = fields[self.seq_col-1]
        try:
          read.qual = fields[self.qual_col-1]
        except (TypeError, IndexError):
          pass
        yield read
    finally:
      if self.input_type == 'path':
        input_iterator.close()


class SamReader(Reader):
  """A simple SAM parser.
  Assumptions:
  Lines starting with "@" with 3 fields are headers. All others are alignments.
  All alignment lines have 11 or more fields. Other lines will be skipped.
  """
  def parser(self):
    input_iterator = self.get_input_iterator()
    try:
      for line in input_iterator:
        fields = line.split('\t')
        if len(fields) < 11:
          continue
        # Skip headers.
        if fields[0].startswith('@') and len(fields[0]) == 3:
          continue
        read = Read(qual_format=self.qual_format)
        read.name = fields[0]
        if read.name:
          read.id = read.name.split()[0]
        read.seq = fields[9]
        read.qual = fields[10].rstrip('\r\n')
        yield read
    finally:
      if self.input_type == 'path':
        input_iterator.close()


class FastaReader(Reader):
  """A simple FASTA parser that reads one sequence at a time into memory."""
  def parser(self):
    input_iterator = self.get_input_iterator()
    try:
      read = None
      while True:
        try:
          line_raw = next(input_iterator)
        except StopIteration:
          if read is not None:
            yield read
          return
        line = line_raw.rstrip('\r\n')
        if line.startswith('>'):
          if read is not None:
            yield read
          read = Read()
          read.name = line[1:]  # remove ">"
          if read.name:
            read.id = read.name.split()[0]
          continue
        else:
          read.seq += line
    finally:
      if self.input_type == 'path':
        input_iterator.close()


class FastqReader(Reader):
  """A simple FASTQ parser. Can handle multi-line sequences, though."""
  def parser(self):
    input_iterator = self.get_input_iterator()
    try:
      read = None
      line_num = 0
      state = 'header'
      while True:
        try:
          line_raw = next(input_iterator)
        except StopIteration:
          if read is not None:
            yield read
          return
        line_num += 1
        line = line_raw.rstrip('\r\n')
        if state == 'header':
          if not line.startswith('@'):
            if line:
              raise FormatError('line state = "header" but line does not start with "@":\n'+line)
            else:
              # Allow empty lines.
              continue
          if read is not None:
            yield read
          read = Read(qual_format=self.qual_format)
          read.name = line[1:]  # remove '@'
          if read.name:
            read.id = read.name.split()[0]
          state = 'sequence'
        elif state == 'sequence':
          if line.startswith('+'):
            state = 'plus'
          else:
            read.seq += line
        elif state == 'plus' or state == 'quality':
          if line.startswith('@') and state == 'quality':
            logging.warning('Looking for more quality scores but line starts with "@". This might '
                            'be a header line and there were fewer quality scores than bases: {}'
                            .format(line[:69]))
          state = 'quality'
          togo = len(read.seq) - len(read.qual)
          read.qual += line[:togo]
          # The end of the quality lines is when we have a quality string as long as the sequence.
          if len(read.qual) >= len(read.seq):
            state = 'header'
    finally:
      if self.input_type == 'path':
        input_iterator.close()


DESCRIPTION = 'Test parser by parsing an input file and printing its contents.'


def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION)
  parser.add_argument('infile', nargs='?', type=argparse.FileType('r'), default=sys.stdin,
    help='Input reads.')
  parser.add_argument('-f', '--format', choices=('fasta', 'fastq', 'sam', 'tsv', 'lines'),
    help='Input read format. Will be detected from the filename, if given.')
  return parser


def main(argv):
  parser = make_argparser()
  args = parser.parse_args(argv[1:])
  if args.format:
    format = args.format
  elif args.infile is sys.stdin:
    fail('Error: Must give a --format if reading from stdin.')
  else:
    ext = os.path.splitext(args.infile.name)[1]
    if ext == '.fq':
      format = 'fastq'
    elif ext == '.fa':
      format = 'fasta'
    elif ext == '.txt':
      format = 'lines'
    else:
      format = ext[1:]
  print('Reading input as format {!r}.'.format(format))
  for i, read in enumerate(getparser(args.infile, filetype=format)):
    print('Read {} id/name: {!r}/{!r}'.format(i+1, read.id, read.name))
    print('Read {} seq:  {!r}'.format(i+1, read.seq))
    print('Read {} qual: {!r}'.format(i+1, read.qual))


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)


if __name__ == '__main__':
  sys.exit(main(sys.argv))
