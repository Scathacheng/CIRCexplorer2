'''
Usage: CIRCexplorer2 align [options] -G GTF (-g GENOME | -i INDEX1 -j INDEX2) \
<fastq>...

Options:
    -h --help                      Show help message.
    -v --version                   Show version.
    -G GTF --gtf=GTF               Annotation GTF file.
    -g GENOME --genome=GENOME      Genome fasta file.
    -i INDEX1 --bowtie1=INDEX1     Index files for Bowtie1.
    -j INDEX2 --bowtie2=INDEX2     Index files for Bowtie2.
    -p THREAD --thread=THREAD      Running threads. [default: 10]
    -o OUT --output=OUT            Output directory. [default: circ_out]
    --bw                           Create BigWig file.
    --scale                        Scale to HPB.
    --no-tophat-fusion             No TopHat-Fusion mapping.
'''

import sys
import os
import os.path
import shutil
import glob
import time
from collections import defaultdict
import pysam
import pybedtools
from file_parse import parse_fusion_bam

__author__ = 'Xiao-Ou Zhang (zhangxiaoou@picb.ac.cn)'

__all__ = ['align']


def align(options):
    local_time = time.strftime('%H:%M:%S', time.localtime(time.time()))
    print('Start CIRCexplorer2 align at %s' % local_time)
    # check output directory
    check_outdir(options['--output'])
    out_dir = os.path.abspath(options['--output'])
    # check index files
    if options['--genome']:  # build index
        prefix1, prefix2 = check_index(0, out_dir, options['--genome'])
    else:  # index exist
        prefix1, prefix2 = check_index(1, out_dir, (options['--bowtie1'],
                                                    options['--bowtie2']))
    # tophat2 mapping
    tophat_map(options['--gtf'], out_dir, prefix2, options['<fastq>'],
               options['--thread'], bw=options['--bw'],
               scale=options['--scale'])
    if not options['--no-tophat-fusion']:
        # tophat fusion mapping
        tophat_fusion_map(out_dir, prefix1, options['--thread'])
    local_time = time.strftime('%H:%M:%S', time.localtime(time.time()))
    print('End CIRCexplorer2 align at %s' % local_time)


def check_outdir(out_dir):
    '''
    1. Clear output directory if not empty
    2. Create essential subdirectories
    '''
    print('Check output directory...')
    # clear output directory if not empty
    if os.path.isdir(out_dir):
        if os.listdir(out_dir):
            print('Warning: the output directory %s is not empty!' % out_dir)
        shutil.rmtree(out_dir)
    # create essential subdirectories
    os.mkdir(out_dir)
    os.mkdir(out_dir + '/bowtie1_index')
    os.mkdir(out_dir + '/bowtie2_index')
    os.mkdir(out_dir + '/tophat')
    os.mkdir(out_dir + '/tophat_fusion')


def check_index(index_flag, out_dir, file):
    '''
    1. Build index for Bowtie1 and Bowtie2 if not exist
    2. Links index files if exist
    '''
    print('Check index files....')
    if index_flag:  # index exist
        # link index files for bowtie1
        print('Link index files for Bowtie1...')
        index1_flag = False
        for f in glob.glob(file[0] + '*'):
            f_abs = os.path.abspath(f)
            f_name = os.path.split(f_abs)[1]
            if f_name.endswith('.rev.1.ebwt'):
                prefix1 = f_name.rsplit('.', 3)[0]
                index1_flag = True
            os.symlink(f_abs, '%s/bowtie1_index/%s' % (out_dir, f_name))
        if not index1_flag:
            sys.exit('Error: your bowtie1_index %s is wrong!' % file[0])
        # link index files for bowtie2
        print('Link index files for Bowtie2...')
        index2_flag = False
        for f in glob.glob(file[1] + '*'):
            f_abs = os.path.abspath(f)
            f_name = os.path.split(f_abs)[1]
            if f_name.endswith('.rev.1.bt2'):
                prefix2 = f_name.rsplit('.', 3)[0]
                index2_flag = True
            os.symlink(f_abs, '%s/bowtie2_index/%s' % (out_dir, f_name))
        if not index2_flag:
            sys.exit('Error: your bowtie2_index %s is wrong!' % file[1])
        return (prefix1, prefix2)
    else:  # index not exist
        prefix = os.path.split(file)[1]
        # build index for bowtie1
        print('Build index for Bowtie1...')
        index_dir = '%s/bowtie1_index/%s' % (out_dir, prefix)
        return_code = os.system('bowtie-build %s %s > %s/bowtie1_index.log' %
                                (file, index_dir, out_dir)) >> 8
        if return_code:
            sys.exit('Error: cannot build index for bowtie1!')
        os.symlink(file, index_dir)
        # build index for bowtie2
        print('Build index for Bowtie2...')
        index_dir = '%s/bowtie2_index/%s' % (out_dir, prefix)
        return_code = os.system('bowtie2-build %s %s > %s/bowtie2_index.log' %
                                (file, index_dir, out_dir)) >> 8
        if return_code:
            sys.exit('Error: cannot build index for bowtie2!')
        os.symlink(file, index_dir)
        return (prefix, prefix)


def tophat_map(gtf, out_dir, prefix, fastq, thread, bw=False, scale=False,
               gtf_flag=1):
    '''
    1. Map reads with TopHat2
    2. Extract unmapped reads
    3. Create BigWig file if needed
    '''
    # tophat2 mapping
    print('Map reads with TopHat2...')
    tophat_cmd = 'tophat2 -g 1 --microexon-search -m 2 '
    if gtf_flag:
        tophat_cmd += '-G %s ' % gtf
    tophat_cmd += '-p %s -o %s ' % (thread, out_dir + '/tophat')
    tophat_cmd += '%s/bowtie2_index/%s ' % (out_dir, prefix) + ','.join(fastq)
    tophat_cmd += ' 2> %s/tophat.log' % out_dir
    print('TopHat2 mapping command:')
    print(tophat_cmd)
    return_code = os.system(tophat_cmd) >> 8
    if return_code:
        sys.exit('Error: cannot map reads with TopHat2!')
    # extract unmapped reads
    print('Extract unmapped reads...')
    unmapped_bam = pybedtools.BedTool('%s/tophat/unmapped.bam' % out_dir)
    unmapped_bam.bam_to_fastq(fq='%s/tophat/unmapped.fastq' % out_dir)
    # create Bigwig file if needed
    if bw:
        print('Create BigWig file...')
        map_bam_fname = '%s/tophat/accepted_hits.bam' % out_dir
        # index bam if not exist
        if not os.path.isfile(map_bam_fname + '.bai'):
            pysam.index(map_bam_fname)
        map_bam = pysam.AlignmentFile(map_bam_fname, 'rb')
        # extract chrom size file
        chrom_size_fname = '%s/tophat/chrom.size' % out_dir
        with open(chrom_size_fname, 'w') as chrom_size_f:
            for seq in map_bam.header['SQ']:
                chrom_size_f.write('%s\t%s\n' % (seq['SN'], seq['LN']))
        if scale:  # scale to HPB
            mapped_reads = map_bam.mapped
            for read in map_bam:
                read_length = read.query_length
                break
            s = 1000000000.0 / mapped_reads / read_length
        else:
            s = 1
        map_bam = pybedtools.BedTool(map_bam_fname)
        bedgraph_fname = '%s/tophat/accepted_hits.bg' % out_dir
        with open(bedgraph_fname, 'w') as bedgraph_f:
            for line in map_bam.genome_coverage(bg=True, g=chrom_size_fname,
                                                scale=s, split=True):
                value = str(int(float(line[3]) + 0.5))
                bedgraph_f.write('\t'.join(line[:3]) + '\t%s\n' % value)
        bigwig_fname = '%s/tophat/accepted_hits.bw' % out_dir
        return_code = os.system('bedGraphToBigWig %s %s %s' %
                                (bedgraph_fname, chrom_size_fname,
                                 bigwig_fname)) >> 8
        if return_code:
            sys.exit('Error: cannot convert bedGraph to BigWig!')


def tophat_fusion_map(out_dir, prefix, thread):
    '''
    1. Map reads with TopHat-Fusion
    2. Extract fusion junction reads
    '''
    # tophat_fusion mapping
    print('Map unmapped reads with TopHat-Fusion...')
    tophat_fusion_cmd = 'tophat2 --fusion-search --keep-fasta-order --bowtie1 '
    tophat_fusion_cmd += '--no-coverage-search '
    tophat_fusion_cmd += '-p %s -o %s ' % (thread, out_dir + '/tophat_fusion')
    tophat_fusion_cmd += '%s/bowtie1_index/%s ' % (out_dir, prefix)
    tophat_fusion_cmd += '%s/tophat/unmapped.fastq ' % out_dir
    tophat_fusion_cmd += '2> %s/tophat_fusion.log' % out_dir
    print('TopHat-Fusion mapping command:')
    print(tophat_fusion_cmd)
    return_code = os.system(tophat_fusion_cmd) >> 8
    if return_code:
        sys.exit('Error: cannot map unmapped reads with TopHat-Fusion!')
    # extract fusion junction reads
    print('Extract fusions junction reads...')
    fusions = defaultdict(int)
    fusion_bam_f = '%s/tophat_fusion/accepted_hits.bam' % out_dir
    for i, read in enumerate(parse_fusion_bam(fusion_bam_f)):
        chrom, strand, start, end = read
        segments = [start, end]
        if (i + 1) % 2 == 1:  # first fragment of fusion junction read
            interval = [start, end]
        else:  # second fragment of fusion junction read
            sta1, end1 = interval
            sta2, end2 = segments
            if end1 < sta2 or end2 < sta1:  # no overlap between fragments
                sta = sta1 if sta1 < sta2 else sta2
                end = end1 if end1 > end2 else end2
                fusions['%s\t%d\t%d' % (chrom, sta, end)] += 1
    total = 0
    with open('%s/fusion_junction.bed' % out_dir, 'w') as outf:
        for i, pos in enumerate(fusions):
            outf.write('%s\tFUSIONJUNC_%d/%d\t0\t+\n' % (pos, i, fusions[pos]))
            total += fusions[pos]
    print('Converted %d fusion reads!' % total)